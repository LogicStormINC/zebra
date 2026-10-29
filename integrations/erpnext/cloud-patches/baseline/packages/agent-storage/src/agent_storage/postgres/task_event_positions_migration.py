"""Canonical Task coordinates; source appends allocate after other transaction locks."""

from agent_storage.postgres.migration_types import Migration
from agent_storage.postgres.task_event_position_guards import TASK_POSITION_GUARDS

TASK_EVENT_POSITIONS_MIGRATION = Migration(
    version=61,
    name="immutable_task_event_positions",
    statements=(
        "ALTER TABLE session_events ADD COLUMN task_id UUID, ADD COLUMN task_sequence BIGINT",
        """ALTER TABLE session_events ADD CONSTRAINT session_events_task_position_pair
           CHECK ((task_id IS NULL) = (task_sequence IS NULL)
                  AND (task_sequence IS NULL OR task_sequence >= 0))""",
        """CREATE UNIQUE INDEX session_events_task_positions
           ON session_events(deployment_namespace,task_id,task_sequence)
           WHERE task_id IS NOT NULL""",
        """CREATE INDEX session_events_unpositioned
           ON session_events(deployment_namespace,session_id,sequence)
           WHERE task_id IS NULL""",
        """ALTER TABLE agent_tasks
           ADD COLUMN next_event_sequence BIGINT NOT NULL DEFAULT 0
               CHECK (next_event_sequence >= 0),
           ADD COLUMN event_position_state TEXT NOT NULL DEFAULT 'legacy'
               CHECK (event_position_state IN ('legacy','validating','assigning','ready')),
           ADD COLUMN event_position_cursor BIGINT NOT NULL DEFAULT -1
               CHECK (event_position_cursor >= -1),
           ADD COLUMN event_index_repair_cursor BIGINT NOT NULL DEFAULT -1
               CHECK (event_index_repair_cursor >= -1),
           ADD COLUMN event_index_repair_highwater BIGINT NOT NULL DEFAULT -1
               CHECK (event_index_repair_highwater >= -1)""",
        """ALTER TABLE execution_segments
           ADD COLUMN event_position_source_cursor BIGINT NOT NULL DEFAULT -1
               CHECK (event_position_source_cursor >= -1),
           ADD COLUMN event_position_source_ready BOOLEAN NOT NULL DEFAULT false""",
        """CREATE INDEX execution_segments_position_pending
           ON execution_segments(deployment_namespace,task_id,segment_index)
           WHERE NOT event_position_source_ready""",
        *TASK_POSITION_GUARDS,
        """CREATE OR REPLACE FUNCTION allocate_task_event_position() RETURNS trigger AS $$
           DECLARE member UUID; segment RECORD; task RECORD; source_row RECORD;
                   previous_task UUID; previous_position BIGINT; indexed RECORD; allocated BIGINT;
           BEGIN
             SELECT task_id INTO member FROM execution_segments
               WHERE deployment_namespace=NEW.deployment_namespace AND session_id=NEW.session_id;
             IF member IS NULL THEN RETURN NULL; END IF;
             -- Last blocking lock domain: callers already own Session/lineage/lease locks.
             PERFORM pg_advisory_xact_lock(
               hashtextextended(NEW.deployment_namespace || ':' || member::text,61));
             -- Deferred trigger: re-read source and membership, not the INSERT's old NEW.
             SELECT task_id,task_sequence,session_id,sequence INTO source_row FROM session_events
               WHERE deployment_namespace=NEW.deployment_namespace AND event_id=NEW.event_id;
             IF NOT FOUND THEN RETURN NULL; END IF;
             SELECT task_id,event_position_source_cursor,event_position_source_ready INTO segment
               FROM execution_segments WHERE deployment_namespace=NEW.deployment_namespace
                 AND session_id=source_row.session_id;
             IF NOT FOUND OR segment.task_id<>member THEN
               RAISE EXCEPTION 'Task Event membership changed' USING ERRCODE='55000';
             END IF;
             SELECT next_event_sequence,event_position_state INTO task FROM agent_tasks
               WHERE deployment_namespace=NEW.deployment_namespace AND task_id=member;
             IF NOT FOUND OR task.event_position_state<>'ready'
                 OR NOT segment.event_position_source_ready THEN
               RAISE EXCEPTION 'Task Event positions require explicit backfill'
                 USING ERRCODE='55000';
             END IF;
             IF source_row.sequence>0 THEN
               SELECT task_id,task_sequence INTO previous_task,previous_position FROM session_events
                 WHERE deployment_namespace=NEW.deployment_namespace
                   AND session_id=source_row.session_id AND sequence=source_row.sequence-1;
               IF NOT FOUND OR previous_task IS DISTINCT FROM member THEN
                 RAISE EXCEPTION 'Task positions require earlier source Events'
                   USING ERRCODE='55000';
               END IF;
             END IF;
             IF source_row.task_id IS NULL THEN
               IF source_row.sequence<>segment.event_position_source_cursor+1 THEN
                 RAISE EXCEPTION 'canonical Task source coverage is incomplete'
                   USING ERRCODE='55000';
               END IF;
               allocated:=task.next_event_sequence;
               IF source_row.sequence>0 AND previous_position>=allocated THEN
                 RAISE EXCEPTION 'Task positions invert source order' USING ERRCODE='55000';
               END IF;
               UPDATE agent_tasks SET next_event_sequence=next_event_sequence+1
                 WHERE deployment_namespace=NEW.deployment_namespace AND task_id=member;
               UPDATE session_events SET task_id=member,task_sequence=allocated
                 WHERE deployment_namespace=NEW.deployment_namespace AND event_id=NEW.event_id;
               UPDATE execution_segments SET event_position_source_cursor=source_row.sequence
                 WHERE deployment_namespace=NEW.deployment_namespace
                   AND session_id=source_row.session_id;
               source_row.task_id:=member;
               source_row.task_sequence:=allocated;
             ELSE
               -- Import/admission can adopt queued INSERTs before this deferred trigger.
               -- Validate their current coordinates, without allocating twice or rewinding.
               IF source_row.task_id<>member OR source_row.task_sequence>=task.next_event_sequence
                   OR source_row.sequence>segment.event_position_source_cursor
                   OR (source_row.sequence>0 AND previous_position>=source_row.task_sequence) THEN
                 RAISE EXCEPTION 'Task Event position conflicts with adopted source'
                   USING ERRCODE='55000';
               END IF;
             END IF;
             INSERT INTO task_event_index
               (deployment_namespace,task_id,task_sequence,event_id,segment_id,segment_sequence)
               VALUES (NEW.deployment_namespace,member,source_row.task_sequence,NEW.event_id,
                       source_row.session_id,source_row.sequence)
               ON CONFLICT (deployment_namespace,event_id) DO NOTHING;
             SELECT task_id,task_sequence,segment_id,segment_sequence INTO indexed
               FROM task_event_index WHERE deployment_namespace=NEW.deployment_namespace
                 AND event_id=NEW.event_id;
             IF (indexed.task_id,indexed.task_sequence,indexed.segment_id,indexed.segment_sequence)
                 IS DISTINCT FROM
                (member,source_row.task_sequence,source_row.session_id,source_row.sequence) THEN
               RAISE EXCEPTION 'derived Task position conflicts with source Event'
                 USING ERRCODE='55000';
             END IF;
             RETURN NULL;
           END; $$ LANGUAGE plpgsql VOLATILE""",
        # Membership can be created after insertion; no immediate WHEN predicate is safe.
        "DROP TRIGGER IF EXISTS session_events_allocate_task_position ON session_events",
        """CREATE CONSTRAINT TRIGGER session_events_allocate_task_position
           AFTER INSERT ON session_events DEFERRABLE INITIALLY DEFERRED
           FOR EACH ROW EXECUTE FUNCTION allocate_task_event_position()""",
    ),
)
