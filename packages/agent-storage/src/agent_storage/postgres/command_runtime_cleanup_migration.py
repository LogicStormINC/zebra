"""v47: bounded fenced claims for existing post-control cleanup obligations."""

from agent_storage.postgres.migration_types import Migration

COMMAND_RUNTIME_CLEANUP_MIGRATION = Migration(
    version=47,
    name="command_runtime_cleanup_claims",
    statements=(
        """CREATE INDEX runtime_instance_revoked_fence ON runtime_instances
           (deployment_namespace,session_id,control_plane_epoch,fencing_token,owner_instance_id,
            created_at,instance_id) WHERE status<>'removed'""",
        """ALTER TABLE command_runtime_cleanup DROP CONSTRAINT command_runtime_cleanup_status_check,
           ADD CONSTRAINT command_runtime_cleanup_status_check
             CHECK(status IN ('pending','cleaning','done','requires_reconciliation')),
           ADD COLUMN available_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
           ADD COLUMN claim_owner TEXT,
           ADD COLUMN claim_fence BIGINT NOT NULL DEFAULT 0,
           ADD COLUMN lease_expires_at TIMESTAMPTZ,
           ADD COLUMN attempts BIGINT NOT NULL DEFAULT 0,
           ADD COLUMN error_code TEXT CHECK(error_code IN
             ('invalid_control_evidence','missing_revoked_fence','engine_unavailable',
              'instance_identity_conflict','creation_unsettled','retry_budget_exhausted'))""",
        """CREATE INDEX command_runtime_cleanup_due ON command_runtime_cleanup
           (deployment_namespace,available_at,accepted_event_id) WHERE status='pending'""",
        """CREATE INDEX command_runtime_cleanup_expired ON command_runtime_cleanup
           (deployment_namespace,lease_expires_at,accepted_event_id) WHERE status='cleaning'""",
    ),
)
