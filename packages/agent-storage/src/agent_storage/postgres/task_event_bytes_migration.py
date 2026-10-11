"""Persist byte metadata without an unbounded upgrade-time body rewrite."""

from agent_storage.postgres.migration_types import Migration

BYTE_BOUND = (
    "octet_length(payload::text) + 768 + 6*("
    "octet_length(COALESCE(idempotency_key,'')) +"
    "octet_length(COALESCE(policy_version,'')) +"
    "octet_length(COALESCE(model_profile,'')))"
)
TASK_EVENT_BYTES_MIGRATION = Migration(
    version=63,
    name="persisted_event_byte_bounds",
    statements=(
        "ALTER TABLE session_events ADD COLUMN event_bytes_bound BIGINT "
        "CHECK (event_bytes_bound > 0)",
        """CREATE FUNCTION compute_event_byte_bound() RETURNS trigger AS $$ BEGIN
           NEW.event_bytes_bound:=octet_length(NEW.payload::text) + 768 + 6*(
             octet_length(COALESCE(NEW.idempotency_key,'')) +
             octet_length(COALESCE(NEW.policy_version,'')) +
             octet_length(COALESCE(NEW.model_profile,'')));
           RETURN NEW; END; $$ LANGUAGE plpgsql""",
        """CREATE TRIGGER session_events_byte_bound
           BEFORE INSERT OR UPDATE OF payload,idempotency_key,policy_version,model_profile,
             event_bytes_bound ON session_events
           FOR EACH ROW EXECUTE FUNCTION compute_event_byte_bound()""",
    ),
)
