"""v81: explicit strict checkpoint recovery, never relabel uncertain programs."""

from agent_storage.postgres.migration_types import Migration

COVERAGE_COMMAND_RECOVERY_MIGRATION = Migration(
    version=81,
    name="coverage_command_checkpoint_recovery",
    statements=(
        """ALTER TABLE command_recovery_attempts
           DROP CONSTRAINT command_recovery_attempts_reason_check,
           ADD CONSTRAINT command_recovery_attempts_reason_check CHECK
             (reason IN ('published_no_handoff','expired_unstarted',
                         'coverage_checkpoint','coverage_continuation')),
           ADD COLUMN coverage_proof JSONB,
           ADD CONSTRAINT command_recovery_coverage_proof CHECK
             ((reason IN ('coverage_checkpoint','coverage_continuation'))
              = (coverage_proof IS NOT NULL))""",
    ),
)
