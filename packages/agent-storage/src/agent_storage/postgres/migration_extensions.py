"""Additive reliability migration tail; individual definitions remain immutable."""

from agent_storage.postgres.command_rollout_shadow_migration import (
    COMMAND_ROLLOUT_SHADOW_MIGRATION,
)
from agent_storage.postgres.command_runtime_cleanup_migration import (
    COMMAND_RUNTIME_CLEANUP_MIGRATION,
)
from agent_storage.postgres.command_wakeup_capacity_migration import COMMAND_CAPACITY_MIGRATION
from agent_storage.postgres.command_wakeup_control_migration import COMMAND_CONTROL_MIGRATION
from agent_storage.postgres.command_wakeup_cutover_migration import COMMAND_CUTOVER_MIGRATION
from agent_storage.postgres.command_wakeup_discovery_migration import COMMAND_DISCOVERY_MIGRATION
from agent_storage.postgres.command_wakeup_handoff_migration import COMMAND_HANDOFF_MIGRATION
from agent_storage.postgres.command_wakeup_message_migration import COMMAND_MESSAGE_MIGRATION
from agent_storage.postgres.command_wakeup_migration import COMMAND_WAKEUP_MIGRATION
from agent_storage.postgres.command_wakeup_pickup_migration import COMMAND_PICKUP_MIGRATION
from agent_storage.postgres.command_wakeup_quarantine_migration import COMMAND_QUARANTINE_MIGRATION
from agent_storage.postgres.command_wakeup_receipts_migration import COMMAND_RECEIPTS_MIGRATION
from agent_storage.postgres.command_wakeup_recovery_migration import COMMAND_RECOVERY_MIGRATION
from agent_storage.postgres.command_wakeup_relay_migration import COMMAND_RELAY_MIGRATION
from agent_storage.postgres.direct_control_migration import DIRECT_CONTROL_MIGRATION
from agent_storage.postgres.runtime_instances_migration import RUNTIME_INSTANCES_MIGRATION

RELIABILITY_MIGRATIONS = (
    COMMAND_WAKEUP_MIGRATION,
    COMMAND_DISCOVERY_MIGRATION,
    COMMAND_RELAY_MIGRATION,
    COMMAND_HANDOFF_MIGRATION,
    COMMAND_RECEIPTS_MIGRATION,
    COMMAND_RECOVERY_MIGRATION,
    COMMAND_MESSAGE_MIGRATION,
    COMMAND_CONTROL_MIGRATION,
    COMMAND_CUTOVER_MIGRATION,
    COMMAND_PICKUP_MIGRATION,
    COMMAND_QUARANTINE_MIGRATION,
    RUNTIME_INSTANCES_MIGRATION,
    COMMAND_RUNTIME_CLEANUP_MIGRATION,
    DIRECT_CONTROL_MIGRATION,
    COMMAND_CAPACITY_MIGRATION,
    COMMAND_ROLLOUT_SHADOW_MIGRATION,
)
