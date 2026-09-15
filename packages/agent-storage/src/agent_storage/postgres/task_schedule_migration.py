"""PostgreSQL v58: user-owned Task schedules and durable firings."""

from agent_storage.postgres.migration_types import Migration

TASK_SCHEDULE_MIGRATION = Migration(
    version=58,
    name="user_task_schedules",
    statements=(
        """
        CREATE TABLE schedule_authority_bindings (
            deployment_namespace TEXT NOT NULL,
            binding_id UUID NOT NULL,
            schedule_id UUID NOT NULL,
            tenant_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            host_app_id TEXT NOT NULL,
            binding_revision BIGINT NOT NULL CHECK (binding_revision >= 1),
            revoked_at TIMESTAMPTZ,
            payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
            PRIMARY KEY (deployment_namespace, binding_id),
            UNIQUE (deployment_namespace, schedule_id, binding_id)
        )
        """,
        """
        CREATE TABLE task_schedules (
            deployment_namespace TEXT NOT NULL,
            schedule_id UUID NOT NULL,
            tenant_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            host_app_id TEXT NOT NULL,
            title TEXT NOT NULL CHECK (length(btrim(title)) > 0),
            status TEXT NOT NULL CHECK (
                status IN ('active', 'paused', 'completed', 'deleted')
            ),
            schedule_version BIGINT NOT NULL CHECK (schedule_version >= 1),
            next_fire_at TIMESTAMPTZ,
            last_fire_at TIMESTAMPTZ,
            authority_binding_id UUID NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
            PRIMARY KEY (deployment_namespace, schedule_id),
            FOREIGN KEY (deployment_namespace, schedule_id, authority_binding_id)
                REFERENCES schedule_authority_bindings (
                    deployment_namespace, schedule_id, binding_id
                ),
            CHECK (updated_at >= created_at),
            CHECK ((status = 'active') = (next_fire_at IS NOT NULL)
                OR status = 'paused')
        )
        """,
        """
        CREATE INDEX task_schedules_due
        ON task_schedules (deployment_namespace, status, next_fire_at, schedule_id)
        """,
        """
        CREATE INDEX task_schedules_owner_recent
        ON task_schedules (
            deployment_namespace, tenant_id, workspace_id, principal_id,
            host_app_id, updated_at DESC, schedule_id
        )
        """,
        """
        CREATE TABLE task_schedule_firings (
            deployment_namespace TEXT NOT NULL,
            fire_id UUID NOT NULL,
            schedule_id UUID NOT NULL,
            schedule_version BIGINT NOT NULL CHECK (schedule_version >= 1),
            scheduled_for TIMESTAMPTZ NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN ('materializing', 'dispatched', 'completed', 'failed', 'skipped')
            ),
            task_id UUID,
            attempt INTEGER NOT NULL CHECK (attempt >= 0),
            failure_code TEXT,
            claimed_by TEXT,
            claim_expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL,
            dispatched_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            PRIMARY KEY (deployment_namespace, fire_id),
            UNIQUE (deployment_namespace, schedule_id, scheduled_for),
            FOREIGN KEY (deployment_namespace, schedule_id)
                REFERENCES task_schedules (deployment_namespace, schedule_id),
            CHECK ((claimed_by IS NULL) = (claim_expires_at IS NULL)),
            CHECK (claim_expires_at IS NULL OR claim_expires_at > created_at),
            CHECK (dispatched_at IS NULL OR task_id IS NOT NULL),
            CHECK ((status IN ('dispatched', 'completed')) = (task_id IS NOT NULL)
                OR status = 'failed'),
            CHECK ((status IN ('completed', 'failed', 'skipped'))
                = (completed_at IS NOT NULL)),
            CHECK ((status IN ('failed', 'skipped')) = (failure_code IS NOT NULL))
        )
        """,
        """
        CREATE INDEX task_schedule_firings_claim
        ON task_schedule_firings (
            deployment_namespace, status, claim_expires_at, scheduled_for, fire_id
        )
        """,
    ),
)
