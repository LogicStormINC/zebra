"""Additive v2 byte bounds and assigned-body guards; v61/v63 stay frozen."""

from agent_storage.postgres.migration_types import Migration
from agent_storage.postgres.task_event_position_guards import TASK_EVENT_BUSINESS_GUARDS

# JSONB may retain numeric scales that Python binary64 serializes differently.
# Charge 24 bytes per number, the longest finite binary64 repr, in addition to
# its existing token. Native JSON path traversal runs only on writes/repair.
BYTE_BOUND = (
    "octet_length(payload::text) + 768 + "
    "24*(SELECT count(*) FROM jsonb_path_query(payload,"
    "'strict $.** ? (@.type() == \"number\")')) + 6*("
    "octet_length(COALESCE(idempotency_key,'')) +"
    "octet_length(COALESCE(policy_version,'')) +"
    "octet_length(COALESCE(model_profile,'')))"
)
NEW_BYTE_BOUND = (
    BYTE_BOUND.replace("payload", "NEW.payload")
    .replace("idempotency_key", "NEW.idempotency_key")
    .replace("policy_version", "NEW.policy_version")
    .replace("model_profile", "NEW.model_profile")
)
TASK_EVENT_SOURCE_BOUNDS_MIGRATION = Migration(
    version=65,
    name="immutable_task_event_business_and_byte_bounds_v2",
    statements=(
        # Metadata-only invalidation: preserve old nonnull cells for audit, while
        # pages already reject the fresh NULL scalar until bounded explicit repair.
        "DROP TRIGGER session_events_byte_bound ON session_events",
        "ALTER TABLE session_events RENAME COLUMN event_bytes_bound TO event_bytes_bound_v1",
        "ALTER TABLE session_events ADD COLUMN event_bytes_bound BIGINT",
        *TASK_EVENT_BUSINESS_GUARDS,
        f"""CREATE OR REPLACE FUNCTION compute_event_byte_bound() RETURNS trigger AS $$ BEGIN
           NEW.event_bytes_bound:={NEW_BYTE_BOUND};
           RETURN NEW; END; $$ LANGUAGE plpgsql""",
        # UPDATE OF binds column numbers, not names. Recreate after the rename
        # so native scalar updates cannot bypass v2 computation.
        """CREATE TRIGGER session_events_byte_bound
           BEFORE INSERT OR UPDATE OF payload,idempotency_key,policy_version,model_profile,
             event_bytes_bound ON session_events
           FOR EACH ROW EXECUTE FUNCTION compute_event_byte_bound()""",
    ),
)
