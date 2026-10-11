"""Additive scalar metadata. Never modify the issued version-62 expressions."""

from agent_storage.postgres.migration_types import Migration

SCALAR_COLUMNS = (
    "task_id,task_sequence,event_id,session_id,sequence,event_type,"
    "replay_command_kind AS command_kind,replay_run_id AS command_run_id,"
    "replay_internal_continuation AS internal_continuation,replay_header_ready"
)
SCALAR_COMMAND = (
    "replay_header_ready AND event_type='session_command_accepted' "
    "AND NOT replay_internal_continuation"
)
SCALAR_EXECUTABLE = f"{SCALAR_COMMAND} AND replay_command_kind IN ('run','resume','message')"
_INCLUDE = (
    "event_id,session_id,sequence,event_type,replay_command_kind,"
    "replay_internal_continuation,replay_header_ready"
)
TASK_REPLAY_SCALAR_HEADER_MIGRATION = Migration(
    version=66,
    name="source_owned_scalar_replay_headers",
    statements=(
        """ALTER TABLE session_events
           ADD COLUMN replay_command_kind TEXT,
           ADD COLUMN replay_run_id TEXT,
           ADD COLUMN replay_internal_continuation BOOLEAN NOT NULL DEFAULT false,
           ADD COLUMN replay_header_ready BOOLEAN NOT NULL DEFAULT false""",
        """CREATE FUNCTION compute_replay_header() RETURNS trigger AS $$ BEGIN
           IF TG_OP='UPDATE' AND OLD.replay_header_ready THEN
             IF (NEW.event_type,NEW.actor,NEW.payload,NEW.replay_command_kind,
                 NEW.replay_run_id,NEW.replay_internal_continuation,NEW.replay_header_ready)
                 IS DISTINCT FROM
                (OLD.event_type,OLD.actor,OLD.payload,OLD.replay_command_kind,
                 OLD.replay_run_id,OLD.replay_internal_continuation,OLD.replay_header_ready) THEN
               RAISE EXCEPTION 'replay header source is immutable' USING ERRCODE='55000';
             END IF;
             RETURN NEW;
           END IF;
           NEW.replay_command_kind:=NULL;
           NEW.replay_run_id:=NULL;
           NEW.replay_internal_continuation:=false;
           IF NEW.event_type='session_command_accepted' THEN
             IF jsonb_typeof(NEW.payload->'kind')='string' THEN
               NEW.replay_command_kind:=NEW.payload->>'kind';
             END IF;
             IF jsonb_typeof(NEW.payload->'payload'->'run_id')='string' THEN
               NEW.replay_run_id:=NEW.payload->'payload'->>'run_id';
             END IF;
             NEW.replay_internal_continuation:=COALESCE(
               NEW.actor='harness' AND NEW.replay_command_kind='resume'
               AND NEW.replay_run_id IS NULL AND
               (NEW.payload->>'idempotency_key' LIKE 'child-wakeup:%'
                OR NEW.payload->>'idempotency_key' LIKE 'client-effect-resume:%'),false);
           END IF;
           NEW.replay_header_ready:=true;
           RETURN NEW; END; $$ LANGUAGE plpgsql""",
        """CREATE TRIGGER session_events_scalar_header
           BEFORE INSERT OR UPDATE OF payload,actor,event_type,replay_command_kind,
             replay_run_id,replay_internal_continuation,replay_header_ready ON session_events
           FOR EACH ROW EXECUTE FUNCTION compute_replay_header()""",
        f"CREATE INDEX session_events_scalar_header ON session_events"
        f"(deployment_namespace,task_id,task_sequence) INCLUDE ({_INCLUDE},replay_run_id) "
        "WHERE task_id IS NOT NULL",
        "CREATE INDEX session_events_scalar_pending ON session_events"
        "(deployment_namespace,task_id,task_sequence) INCLUDE (event_id,event_bytes_bound) "
        "WHERE NOT replay_header_ready",
        f"CREATE INDEX session_events_scalar_run_command ON session_events"
        f"(deployment_namespace,task_id,replay_run_id,task_sequence) INCLUDE ({_INCLUDE}) "
        f"WHERE {SCALAR_COMMAND}",
        f"CREATE INDEX session_events_scalar_run_executable ON session_events"
        f"(deployment_namespace,task_id,replay_run_id,task_sequence) INCLUDE ({_INCLUDE}) "
        f"WHERE {SCALAR_EXECUTABLE}",
        "CREATE INDEX session_events_scalar_executable_order ON session_events"
        f"(deployment_namespace,task_id,task_sequence) WHERE {SCALAR_EXECUTABLE}",
        "CREATE INDEX session_events_scalar_command_order ON session_events"
        f"(deployment_namespace,task_id,task_sequence) WHERE {SCALAR_COMMAND}",
    ),
)
