"""Allow independent Task admissions to share the projector configuration lock."""

from agent_storage.postgres.agui_profile_routing_migration import AGUI_PROFILE_ROUTING_MIGRATION
from agent_storage.postgres.migration_types import Migration

PROJECTION_WORK_SHARED_LOCK_MIGRATION = Migration(
    version=122,
    name="projection_work_shared_admission_lock",
    statements=(
        AGUI_PROFILE_ROUTING_MIGRATION.statements[0].replace(
            "pg_advisory_xact_lock(68,", "pg_advisory_xact_lock_shared(68,", 1
        ),
    ),
)
