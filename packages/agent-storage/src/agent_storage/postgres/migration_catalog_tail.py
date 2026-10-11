"""Latest additive migrations kept separate from the primary catalog."""

from agent_storage.postgres.agent_registry_migration import AGENT_REGISTRY_MIGRATION
from agent_storage.postgres.artifact_payload_migration import ARTIFACT_PAYLOAD_MIGRATION
from agent_storage.postgres.control_plane_migration import CONTROL_PLANE_MIGRATION
from agent_storage.postgres.coverage_authority_migration import COVERAGE_AUTHORITY_MIGRATION
from agent_storage.postgres.coverage_command_recovery_migration import (
    COVERAGE_COMMAND_RECOVERY_MIGRATION,
)
from agent_storage.postgres.coverage_delta_indexes_migration import COVERAGE_DELTA_INDEXES_MIGRATION
from agent_storage.postgres.coverage_execution_migration import COVERAGE_EXECUTION_MIGRATION
from agent_storage.postgres.coverage_execution_receipt_migration import (
    COVERAGE_EXECUTION_RECEIPT_MIGRATION,
)
from agent_storage.postgres.coverage_execution_source_migration import (
    COVERAGE_EXECUTION_SOURCE_MIGRATION,
)
from agent_storage.postgres.coverage_membership_migration import COVERAGE_MEMBERSHIP_MIGRATION
from agent_storage.postgres.coverage_migration import COVERAGE_MIGRATION
from agent_storage.postgres.coverage_model_migration import COVERAGE_MODEL_MIGRATION
from agent_storage.postgres.coverage_model_revision_migration import (
    COVERAGE_MODEL_REVISION_MIGRATION,
)
from agent_storage.postgres.coverage_model_summary_migration import COVERAGE_MODEL_SUMMARY_MIGRATION
from agent_storage.postgres.coverage_model_volume_migration import COVERAGE_MODEL_VOLUME_MIGRATION
from agent_storage.postgres.coverage_proof_indexes_migration import COVERAGE_PROOF_INDEXES_MIGRATION
from agent_storage.postgres.coverage_task_summary_migration import COVERAGE_TASK_SUMMARY_MIGRATION
from agent_storage.postgres.delivery_transaction_migration import DELIVERY_TRANSACTION_MIGRATION
from agent_storage.postgres.full_gateway_migration import FULL_GATEWAY_MIGRATION
from agent_storage.postgres.governed_memory_migration import GOVERNED_MEMORY_MIGRATION
from agent_storage.postgres.handoff_migration import HANDOFF_MIGRATION
from agent_storage.postgres.host_auth_migration import HOST_AUTH_MIGRATION
from agent_storage.postgres.memory_delivery_migration import MEMORY_DELIVERY_MIGRATION
from agent_storage.postgres.migration_recovery_migration import MIGRATION_RECOVERY_MIGRATION
from agent_storage.postgres.native_memory_migration import NATIVE_MEMORY_MIGRATION
from agent_storage.postgres.provider_continuation_migration import PROVIDER_CONTINUATION_MIGRATION
from agent_storage.postgres.task_schedule_migration import TASK_SCHEDULE_MIGRATION
from agent_storage.postgres.tool_profile_constraint_migration import (
    TOOL_PROFILE_CONSTRAINT_MIGRATION,
)
from agent_storage.postgres.user_personalization_migration import USER_PERSONALIZATION_MIGRATION
from agent_storage.postgres.workspace_control_migration import WORKSPACE_CONTROL_MIGRATION

STORAGE_AUTHORITY_MIGRATIONS = (
    HANDOFF_MIGRATION,
    ARTIFACT_PAYLOAD_MIGRATION,
    GOVERNED_MEMORY_MIGRATION,
    MEMORY_DELIVERY_MIGRATION,
    NATIVE_MEMORY_MIGRATION,
    PROVIDER_CONTINUATION_MIGRATION,
    CONTROL_PLANE_MIGRATION,
    DELIVERY_TRANSACTION_MIGRATION,
    MIGRATION_RECOVERY_MIGRATION,
    HOST_AUTH_MIGRATION,
    WORKSPACE_CONTROL_MIGRATION,
    AGENT_REGISTRY_MIGRATION,
)

LATEST_MIGRATIONS = (
    TOOL_PROFILE_CONSTRAINT_MIGRATION,
    TASK_SCHEDULE_MIGRATION,
    USER_PERSONALIZATION_MIGRATION,
    FULL_GATEWAY_MIGRATION,
    COVERAGE_MIGRATION,
    COVERAGE_EXECUTION_MIGRATION,
    COVERAGE_MODEL_MIGRATION,
    COVERAGE_COMMAND_RECOVERY_MIGRATION,
    COVERAGE_EXECUTION_RECEIPT_MIGRATION,
    COVERAGE_EXECUTION_SOURCE_MIGRATION,
    COVERAGE_MODEL_REVISION_MIGRATION,
    COVERAGE_MODEL_SUMMARY_MIGRATION,
    COVERAGE_TASK_SUMMARY_MIGRATION,
    COVERAGE_AUTHORITY_MIGRATION,
    COVERAGE_MODEL_VOLUME_MIGRATION,
    COVERAGE_DELTA_INDEXES_MIGRATION,
    COVERAGE_MEMBERSHIP_MIGRATION,
    COVERAGE_PROOF_INDEXES_MIGRATION,
)
