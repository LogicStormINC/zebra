"""Latest additive migrations kept separate from the primary catalog."""
from agent_storage.postgres.http_input_attachment_migration import HTTP_INPUT_ATTACHMENT_MIGRATION

from agent_storage.postgres.agent_registry_migration import AGENT_REGISTRY_MIGRATION
from agent_storage.postgres.artifact_payload_migration import ARTIFACT_PAYLOAD_MIGRATION
from agent_storage.postgres.command_coverage_admission_migration import (
    COMMAND_COVERAGE_ADMISSION_MIGRATION,
)
from agent_storage.postgres.command_read_state_migration import COMMAND_READ_STATE_MIGRATION
from agent_storage.postgres.control_plane_migration import CONTROL_PLANE_MIGRATION
from agent_storage.postgres.coverage_authority_migration import COVERAGE_AUTHORITY_MIGRATION
from agent_storage.postgres.coverage_command_recovery_migration import (
    COVERAGE_COMMAND_RECOVERY_MIGRATION,
)
from agent_storage.postgres.coverage_delta_indexes_migration import COVERAGE_DELTA_INDEXES_MIGRATION
from agent_storage.postgres.coverage_execution_migration import COVERAGE_EXECUTION_MIGRATION
from agent_storage.postgres.coverage_execution_positions_migration import (
    COVERAGE_EXECUTION_POSITIONS_MIGRATION,
)
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
from agent_storage.postgres.coverage_model_source_positions_migration import (
    COVERAGE_MODEL_SOURCE_POSITIONS_MIGRATION,
)
from agent_storage.postgres.coverage_model_summary_migration import COVERAGE_MODEL_SUMMARY_MIGRATION
from agent_storage.postgres.coverage_model_volume_migration import COVERAGE_MODEL_VOLUME_MIGRATION
from agent_storage.postgres.coverage_proof_indexes_migration import COVERAGE_PROOF_INDEXES_MIGRATION
from agent_storage.postgres.coverage_task_summary_migration import COVERAGE_TASK_SUMMARY_MIGRATION
from agent_storage.postgres.delivery_transaction_migration import DELIVERY_TRANSACTION_MIGRATION
from agent_storage.postgres.execution_input_compaction_migration import (
    EXECUTION_INPUT_COMPACTION_MIGRATION,
)
from agent_storage.postgres.execution_inputs_migration import EXECUTION_INPUTS_MIGRATION
from agent_storage.postgres.full_gateway_migration import FULL_GATEWAY_MIGRATION
from agent_storage.postgres.governed_memory_migration import GOVERNED_MEMORY_MIGRATION
from agent_storage.postgres.handoff_migration import HANDOFF_MIGRATION
from agent_storage.postgres.host_auth_migration import HOST_AUTH_MIGRATION
from agent_storage.postgres.memory_delivery_migration import MEMORY_DELIVERY_MIGRATION
from agent_storage.postgres.migration_recovery_migration import MIGRATION_RECOVERY_MIGRATION
from agent_storage.postgres.native_memory_migration import NATIVE_MEMORY_MIGRATION
from agent_storage.postgres.plugin_installations_migration import PLUGIN_INSTALLATIONS_MIGRATION
from agent_storage.postgres.projection_source_metadata_migration import (
    TASK_PROJECTION_SOURCE_METADATA_MIGRATION,
)
from agent_storage.postgres.projection_trigger_plan_migration import (
    TASK_PROJECTION_TRIGGER_PLAN_MIGRATION,
)
from agent_storage.postgres.projection_work_classification_migration import (
    TASK_PROJECTION_WORK_CLASSIFICATION_MIGRATION,
)
from agent_storage.postgres.projection_work_fanout_migration import (
    TASK_PROJECTION_WORK_FANOUT_MIGRATION,
)
from agent_storage.postgres.projection_work_migration import TASK_PROJECTION_WORK_MIGRATION
from agent_storage.postgres.projection_work_routing_migration import (
    TASK_PROJECTION_WORK_ROUTING_MIGRATION,
)
from agent_storage.postgres.provider_continuation_migration import PROVIDER_CONTINUATION_MIGRATION
from agent_storage.postgres.research_web_profile_migration import RESEARCH_WEB_PROFILE_MIGRATION
from agent_storage.postgres.session_observation_headers_migration import (
    SESSION_OBSERVATION_HEADERS_MIGRATION,
)
from agent_storage.postgres.session_recovery_migration import SESSION_RECOVERY_MIGRATION
from agent_storage.postgres.stream_hint_relay_migration import STREAM_HINT_RELAY_MIGRATION
from agent_storage.postgres.task_event_bytes_migration import TASK_EVENT_BYTES_MIGRATION
from agent_storage.postgres.task_event_positions_migration import TASK_EVENT_POSITIONS_MIGRATION
from agent_storage.postgres.task_event_source_bounds_migration import (
    TASK_EVENT_SOURCE_BOUNDS_MIGRATION,
)
from agent_storage.postgres.task_projection_checkpoints_migration import (
    TASK_PROJECTION_CHECKPOINTS_MIGRATION,
)
from agent_storage.postgres.task_projection_coverage_cells_migration import (
    TASK_PROJECTION_COVERAGE_CELLS_MIGRATION,
)
from agent_storage.postgres.task_read_summary_migration import TASK_READ_SUMMARY_MIGRATION
from agent_storage.postgres.task_replay_coverage_privacy_migration import (
    TASK_REPLAY_COVERAGE_PRIVACY_MIGRATION,
)
from agent_storage.postgres.task_replay_header_migration import TASK_REPLAY_HEADER_MIGRATION
from agent_storage.postgres.task_replay_scalar_header_migration import (
    TASK_REPLAY_SCALAR_HEADER_MIGRATION,
)
from agent_storage.postgres.task_schedule_migration import TASK_SCHEDULE_MIGRATION
from agent_storage.postgres.tool_profile_constraint_migration import (
    TOOL_PROFILE_CONSTRAINT_MIGRATION,
)
from agent_storage.postgres.user_personalization_migration import USER_PERSONALIZATION_MIGRATION
from agent_storage.postgres.worker_capability_migration import WORKER_CAPABILITY_MIGRATION
from agent_storage.postgres.worker_continuation_migration import WORKER_CONTINUATION_MIGRATION
from agent_storage.postgres.worker_progress_migration import WORKER_PROGRESS_MIGRATION
from agent_storage.postgres.worker_replay_migration import WORKER_REPLAY_MIGRATION
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
    TASK_EVENT_POSITIONS_MIGRATION,
    TASK_REPLAY_HEADER_MIGRATION,
    TASK_EVENT_BYTES_MIGRATION,
    TASK_PROJECTION_CHECKPOINTS_MIGRATION,
    TASK_EVENT_SOURCE_BOUNDS_MIGRATION,
    TASK_REPLAY_SCALAR_HEADER_MIGRATION,
    TASK_PROJECTION_SOURCE_METADATA_MIGRATION,
    TASK_PROJECTION_WORK_MIGRATION,
    SESSION_OBSERVATION_HEADERS_MIGRATION,
    WORKER_PROGRESS_MIGRATION,
    TASK_READ_SUMMARY_MIGRATION,
    SESSION_RECOVERY_MIGRATION,
    EXECUTION_INPUTS_MIGRATION,
    EXECUTION_INPUT_COMPACTION_MIGRATION,
    WORKER_REPLAY_MIGRATION,
    COMMAND_READ_STATE_MIGRATION,
    COVERAGE_MIGRATION,
    COVERAGE_EXECUTION_MIGRATION,
    COVERAGE_MODEL_MIGRATION,
    COVERAGE_COMMAND_RECOVERY_MIGRATION,
    WORKER_CAPABILITY_MIGRATION,
    COMMAND_COVERAGE_ADMISSION_MIGRATION,
    COVERAGE_EXECUTION_RECEIPT_MIGRATION,
    COVERAGE_EXECUTION_SOURCE_MIGRATION,
    WORKER_CONTINUATION_MIGRATION,
    COVERAGE_MODEL_REVISION_MIGRATION,
    COVERAGE_MODEL_SUMMARY_MIGRATION,
    COVERAGE_TASK_SUMMARY_MIGRATION,
    COVERAGE_AUTHORITY_MIGRATION,
    COVERAGE_MODEL_VOLUME_MIGRATION,
    COVERAGE_DELTA_INDEXES_MIGRATION,
    COVERAGE_MEMBERSHIP_MIGRATION,
    COVERAGE_PROOF_INDEXES_MIGRATION,
    TASK_PROJECTION_COVERAGE_CELLS_MIGRATION,
    COVERAGE_MODEL_SOURCE_POSITIONS_MIGRATION,
    TASK_REPLAY_COVERAGE_PRIVACY_MIGRATION,
    TASK_PROJECTION_WORK_ROUTING_MIGRATION,
    COVERAGE_EXECUTION_POSITIONS_MIGRATION,
    TASK_PROJECTION_WORK_FANOUT_MIGRATION,
    STREAM_HINT_RELAY_MIGRATION,
    TASK_PROJECTION_WORK_CLASSIFICATION_MIGRATION,
    TASK_PROJECTION_TRIGGER_PLAN_MIGRATION,
    RESEARCH_WEB_PROFILE_MIGRATION,
    PLUGIN_INSTALLATIONS_MIGRATION,
    HTTP_INPUT_ATTACHMENT_MIGRATION,
)
