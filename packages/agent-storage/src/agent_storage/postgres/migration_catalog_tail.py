"""Latest additive migrations kept separate from the primary catalog."""

from agent_storage.postgres.command_read_state_migration import COMMAND_READ_STATE_MIGRATION
from agent_storage.postgres.coverage_migration import COVERAGE_MIGRATION
from agent_storage.postgres.execution_input_compaction_migration import (
    EXECUTION_INPUT_COMPACTION_MIGRATION,
)
from agent_storage.postgres.execution_inputs_migration import EXECUTION_INPUTS_MIGRATION
from agent_storage.postgres.full_gateway_migration import FULL_GATEWAY_MIGRATION
from agent_storage.postgres.projection_source_metadata_migration import (
    TASK_PROJECTION_SOURCE_METADATA_MIGRATION,
)
from agent_storage.postgres.projection_work_migration import TASK_PROJECTION_WORK_MIGRATION
from agent_storage.postgres.session_observation_headers_migration import (
    SESSION_OBSERVATION_HEADERS_MIGRATION,
)
from agent_storage.postgres.session_recovery_migration import SESSION_RECOVERY_MIGRATION
from agent_storage.postgres.task_event_bytes_migration import TASK_EVENT_BYTES_MIGRATION
from agent_storage.postgres.task_event_positions_migration import TASK_EVENT_POSITIONS_MIGRATION
from agent_storage.postgres.task_event_source_bounds_migration import (
    TASK_EVENT_SOURCE_BOUNDS_MIGRATION,
)
from agent_storage.postgres.task_projection_checkpoints_migration import (
    TASK_PROJECTION_CHECKPOINTS_MIGRATION,
)
from agent_storage.postgres.task_read_summary_migration import TASK_READ_SUMMARY_MIGRATION
from agent_storage.postgres.task_replay_header_migration import TASK_REPLAY_HEADER_MIGRATION
from agent_storage.postgres.task_replay_scalar_header_migration import (
    TASK_REPLAY_SCALAR_HEADER_MIGRATION,
)
from agent_storage.postgres.task_schedule_migration import TASK_SCHEDULE_MIGRATION
from agent_storage.postgres.tool_profile_constraint_migration import (
    TOOL_PROFILE_CONSTRAINT_MIGRATION,
)
from agent_storage.postgres.user_personalization_migration import USER_PERSONALIZATION_MIGRATION
from agent_storage.postgres.worker_progress_migration import WORKER_PROGRESS_MIGRATION
from agent_storage.postgres.worker_replay_migration import WORKER_REPLAY_MIGRATION

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
)
