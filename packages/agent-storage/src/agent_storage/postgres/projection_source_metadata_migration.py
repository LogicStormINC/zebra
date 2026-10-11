"""v67: source-owned scalar handoffs and indexed contiguous Segment blocks."""

from agent_storage.postgres.migration_types import Migration

TASK_PROJECTION_SOURCE_METADATA_MIGRATION = Migration(
    version=67,
    name="indexed_projection_source_metadata",
    statements=(
        """ALTER TABLE session_events ADD COLUMN projection_handoff_id UUID,
           ADD COLUMN projection_peer_segment_id UUID,
           ADD COLUMN projection_metadata_ready BOOLEAN NOT NULL DEFAULT false,
           ADD COLUMN projection_block_start BIGINT CHECK(projection_block_start>=0)""",
        """CREATE TABLE task_projection_source_heads (
           deployment_namespace TEXT NOT NULL,task_id UUID NOT NULL,
           through_sequence BIGINT NOT NULL DEFAULT -1 CHECK(through_sequence>=-1),
           repair_cursor BIGINT NOT NULL DEFAULT -1 CHECK(repair_cursor>=-1),
           repair_highwater BIGINT NOT NULL DEFAULT -1 CHECK(repair_highwater>=-1),
           PRIMARY KEY(deployment_namespace,task_id))""",
        """CREATE TABLE task_projection_blocks (
           deployment_namespace TEXT NOT NULL,task_id UUID NOT NULL,segment_id UUID NOT NULL,
           first_task_sequence BIGINT NOT NULL CHECK(first_task_sequence>=0),
           last_task_sequence BIGINT NOT NULL,
           first_segment_sequence BIGINT NOT NULL CHECK(first_segment_sequence>=0),
           last_segment_sequence BIGINT NOT NULL,previous_block_start BIGINT,
           PRIMARY KEY(deployment_namespace,task_id,first_task_sequence),
           CHECK(last_task_sequence>=first_task_sequence),
           CHECK(last_task_sequence-first_task_sequence=last_segment_sequence-first_segment_sequence),
           CHECK(previous_block_start IS NULL OR
                 previous_block_start BETWEEN 0 AND first_task_sequence-1),
           CHECK((previous_block_start IS NULL)=(first_segment_sequence=0)))""",
        "CREATE INDEX task_projection_blocks_segment ON task_projection_blocks"
        "(deployment_namespace,task_id,segment_id,first_task_sequence)",
        "CREATE INDEX session_events_projection_header ON session_events"
        "(deployment_namespace,task_id,task_sequence) INCLUDE "
        "(event_id,session_id,sequence,event_type,"
        "projection_handoff_id,projection_peer_segment_id,projection_metadata_ready,projection_block_start)",
        "CREATE INDEX session_events_projection_pending ON session_events"
        "(deployment_namespace,task_id,task_sequence) "
        "WHERE NOT projection_metadata_ready OR projection_block_start IS NULL",
        "CREATE INDEX session_events_projection_block ON session_events"
        "(deployment_namespace,task_id,projection_block_start,task_sequence) "
        "INCLUDE (session_id,sequence)",
        "CREATE INDEX session_events_projection_receive ON session_events"
        "(deployment_namespace,task_id,session_id,task_sequence)"
        " WHERE event_type='session_handoff_received'",
        "CREATE INDEX session_events_projection_receive_identity ON session_events"
        "(deployment_namespace,task_id,session_id,projection_handoff_id,task_sequence)"
        " WHERE event_type='session_handoff_received'",
        "CREATE INDEX session_events_projection_commit ON session_events"
        "(deployment_namespace,task_id,session_id,projection_handoff_id,task_sequence)"
        " WHERE event_type='session_handoff_committed'",
        """CREATE FUNCTION compute_projection_source_metadata() RETURNS trigger AS $$ BEGIN
           IF TG_OP='INSERT' AND NEW.projection_block_start IS NOT NULL THEN
             RAISE EXCEPTION 'projection metadata insertion must use source defaults'
               USING ERRCODE='55000';
           END IF;
           IF TG_OP='UPDATE' AND OLD.projection_metadata_ready THEN
             IF (NEW.payload,NEW.actor,NEW.event_type,NEW.projection_handoff_id,
                 NEW.projection_peer_segment_id,NEW.projection_metadata_ready) IS DISTINCT FROM
                (OLD.payload,OLD.actor,OLD.event_type,OLD.projection_handoff_id,
                 OLD.projection_peer_segment_id,OLD.projection_metadata_ready) THEN
               RAISE EXCEPTION 'projection metadata source is immutable' USING ERRCODE='55000';
             END IF;
             RETURN NEW;
           END IF;
           NEW.projection_handoff_id:=NULL; NEW.projection_peer_segment_id:=NULL;
           IF NEW.event_type IN ('session_handoff_committed','session_handoff_received') THEN
             IF jsonb_typeof(NEW.payload->'handoff_id') IS DISTINCT FROM 'string' THEN
               RAISE EXCEPTION 'invalid handoff metadata' USING ERRCODE='55000';
             END IF;
             NEW.projection_handoff_id:=(NEW.payload->>'handoff_id')::uuid;
             IF NEW.event_type='session_handoff_committed' THEN
               IF jsonb_typeof(NEW.payload->'target_session_id') IS DISTINCT FROM 'string' THEN
                 RAISE EXCEPTION 'invalid handoff metadata' USING ERRCODE='55000';
               END IF;
               NEW.projection_peer_segment_id:=(NEW.payload->>'target_session_id')::uuid;
             ELSE
               IF jsonb_typeof(NEW.payload->'parent_session_id') IS DISTINCT FROM 'string' THEN
                 RAISE EXCEPTION 'invalid handoff metadata' USING ERRCODE='55000';
               END IF;
               NEW.projection_peer_segment_id:=(NEW.payload->>'parent_session_id')::uuid;
             END IF;
             IF NEW.projection_peer_segment_id=NEW.session_id THEN
               RAISE EXCEPTION 'invalid handoff metadata' USING ERRCODE='55000';
             END IF;
           END IF;
           NEW.projection_metadata_ready:=true;
           RETURN NEW; END; $$ LANGUAGE plpgsql""",
        """CREATE TRIGGER session_events_projection_metadata BEFORE INSERT OR UPDATE OF
           payload,actor,event_type,projection_handoff_id,projection_peer_segment_id,
           projection_metadata_ready ON session_events FOR EACH ROW
           EXECUTE FUNCTION compute_projection_source_metadata()""",
        """CREATE FUNCTION write_projection_source_metadata(ns TEXT,eid UUID) RETURNS void AS $$
           DECLARE src RECORD; head RECORD; prev RECORD; global_block RECORD;
                   first_src RECORD; last_src RECORD; stored RECORD;
                   block_start BIGINT; predecessor BIGINT;
           BEGIN
             UPDATE session_events SET projection_metadata_ready=true
               WHERE deployment_namespace=ns AND event_id=eid AND NOT projection_metadata_ready;
             SELECT e.task_id,e.task_sequence,e.session_id,e.sequence,e.projection_block_start
               INTO src FROM session_events e JOIN agent_tasks t
                 ON t.deployment_namespace=ns AND t.task_id=e.task_id
               JOIN execution_segments m ON m.deployment_namespace=ns AND m.session_id=e.session_id
                 AND m.task_id=e.task_id WHERE e.deployment_namespace=ns AND e.event_id=eid
               FOR UPDATE OF e;
             IF NOT FOUND OR src.task_id IS NULL THEN RETURN; END IF;
             INSERT INTO task_projection_source_heads(deployment_namespace,task_id)
               VALUES (ns,src.task_id) ON CONFLICT DO NOTHING;
             SELECT through_sequence INTO head FROM task_projection_source_heads
               WHERE deployment_namespace=ns AND task_id=src.task_id FOR UPDATE;
             IF src.task_sequence>head.through_sequence+1 THEN RETURN; END IF;
             IF src.task_sequence=head.through_sequence+1 THEN
               SELECT first_task_sequence,last_segment_sequence INTO prev
                 FROM task_projection_blocks
                 WHERE deployment_namespace=ns AND task_id=src.task_id AND segment_id=src.session_id
                 ORDER BY first_task_sequence DESC LIMIT 1;
               IF src.sequence<>COALESCE(prev.last_segment_sequence+1,0) THEN
                 RAISE EXCEPTION 'projection metadata conflicts with source order'
                   USING ERRCODE='55000';
               END IF;
               SELECT b.first_task_sequence,b.segment_id INTO global_block
                 FROM session_events e JOIN task_projection_blocks b
                 ON b.deployment_namespace=ns AND b.task_id=e.task_id
                   AND b.first_task_sequence=e.projection_block_start
                 WHERE e.deployment_namespace=ns AND e.task_id=src.task_id
                   AND e.task_sequence=head.through_sequence;
               IF global_block.segment_id=src.session_id THEN
                 block_start:=global_block.first_task_sequence;
                 UPDATE task_projection_blocks SET last_task_sequence=src.task_sequence,
                   last_segment_sequence=src.sequence WHERE deployment_namespace=ns
                   AND task_id=src.task_id AND first_task_sequence=block_start;
               ELSE
                 block_start:=src.task_sequence;
                 INSERT INTO task_projection_blocks VALUES
                   (ns,src.task_id,src.session_id,block_start,block_start,
                    src.sequence,src.sequence,prev.first_task_sequence);
               END IF;
               UPDATE session_events SET projection_block_start=block_start
                 WHERE deployment_namespace=ns AND event_id=eid;
               UPDATE task_projection_source_heads SET through_sequence=src.task_sequence
                 WHERE deployment_namespace=ns AND task_id=src.task_id;
             ELSE
               IF src.projection_block_start IS NULL THEN
                 RAISE EXCEPTION 'projection metadata has missing coverage' USING ERRCODE='55000';
               END IF;
               block_start:=src.projection_block_start;
               SELECT task_sequence,session_id,sequence INTO first_src FROM session_events
                 WHERE deployment_namespace=ns AND task_id=src.task_id
                   AND projection_block_start=block_start
                 ORDER BY task_sequence LIMIT 1;
               SELECT task_sequence,session_id,sequence INTO last_src FROM session_events
                 WHERE deployment_namespace=ns AND task_id=src.task_id
                   AND projection_block_start=block_start
                 ORDER BY task_sequence DESC LIMIT 1;
               IF first_src.task_sequence<>block_start OR first_src.session_id<>last_src.session_id
                 OR last_src.task_sequence-first_src.task_sequence<>
                    last_src.sequence-first_src.sequence THEN
                 RAISE EXCEPTION 'projection block conflicts with source' USING ERRCODE='55000';
               END IF;
               predecessor:=NULL;
               IF first_src.sequence>0 THEN
                 SELECT projection_block_start INTO predecessor FROM session_events
                   WHERE deployment_namespace=ns AND session_id=first_src.session_id
                     AND sequence=first_src.sequence-1 AND task_id=src.task_id;
                 IF predecessor IS NULL OR predecessor>=block_start THEN
                   RAISE EXCEPTION 'missing same-Segment block predecessor' USING ERRCODE='55000';
                 END IF;
               END IF;
               INSERT INTO task_projection_blocks VALUES
                 (ns,src.task_id,first_src.session_id,block_start,last_src.task_sequence,
                  first_src.sequence,last_src.sequence,predecessor) ON CONFLICT DO NOTHING;
               SELECT segment_id,first_task_sequence,last_task_sequence,first_segment_sequence,
                      last_segment_sequence,previous_block_start INTO stored
                 FROM task_projection_blocks WHERE deployment_namespace=ns AND task_id=src.task_id
                   AND first_task_sequence=block_start;
               IF (stored.segment_id,stored.first_task_sequence,stored.last_task_sequence,
                   stored.first_segment_sequence,stored.last_segment_sequence,stored.previous_block_start)
                   IS DISTINCT FROM (first_src.session_id,block_start,last_src.task_sequence,
                                     first_src.sequence,last_src.sequence,predecessor) THEN
                 RAISE EXCEPTION 'projection block conflicts with source' USING ERRCODE='55000';
               END IF;
             END IF;
           END; $$ LANGUAGE plpgsql""",
        """CREATE FUNCTION record_projection_source_assignment() RETURNS trigger AS $$ BEGIN
           PERFORM write_projection_source_metadata(NEW.deployment_namespace,NEW.event_id);
           RETURN NULL; END; $$ LANGUAGE plpgsql""",
        """CREATE TRIGGER session_events_projection_assignment AFTER UPDATE OF task_id,task_sequence
           ON session_events FOR EACH ROW WHEN (NEW.task_id IS NOT NULL)
           EXECUTE FUNCTION record_projection_source_assignment()""",
        """CREATE FUNCTION guard_projection_block_coordinate() RETURNS trigger AS $$ BEGIN
           IF (OLD.projection_block_start IS NOT NULL AND NEW.projection_block_start
               IS DISTINCT FROM OLD.projection_block_start) OR NOT EXISTS (
             SELECT 1 FROM task_projection_blocks
             WHERE deployment_namespace=NEW.deployment_namespace
             AND task_id=NEW.task_id AND segment_id=NEW.session_id
             AND first_task_sequence=NEW.projection_block_start
             AND NEW.task_sequence BETWEEN first_task_sequence AND last_task_sequence
             AND NEW.sequence=first_segment_sequence+NEW.task_sequence-first_task_sequence) THEN
             RAISE EXCEPTION 'projection block conflicts with source' USING ERRCODE='55000';
           END IF;
           RETURN NEW; END; $$ LANGUAGE plpgsql""",
        """CREATE TRIGGER session_events_projection_coordinate
           BEFORE UPDATE OF projection_block_start
           ON session_events FOR EACH ROW EXECUTE FUNCTION guard_projection_block_coordinate()""",
    ),
)
