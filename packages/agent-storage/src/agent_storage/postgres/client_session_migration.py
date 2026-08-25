"""Migration v32: client sessions, mounts, run bindings and control leases."""

from agent_storage.postgres.migration_types import Migration

CLIENT_SESSION_MIGRATION = Migration(
    version=32,
    name="client_sessions",
    statements=(
        """
        CREATE TABLE client_sessions (
            deployment_namespace TEXT NOT NULL,
            client_session_id UUID NOT NULL,
            host_app_id TEXT NOT NULL,
            namespace_id TEXT NOT NULL,
            frontend_app_id TEXT NOT NULL,
            origin TEXT NOT NULL,
            user_ref TEXT NOT NULL,
            profile_digest TEXT NOT NULL
                CHECK (profile_digest ~ '^[0-9a-f]{64}$'),
            grant_json JSONB NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'expired', 'closed')),
            ui_revision BIGINT NOT NULL DEFAULT 0 CHECK (ui_revision >= 0),
            mounted_snapshot_digest TEXT
                CHECK (mounted_snapshot_digest IS NULL
                       OR mounted_snapshot_digest ~ '^[0-9a-f]{64}$'),
            created_at TIMESTAMPTZ NOT NULL,
            heartbeat_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (deployment_namespace, client_session_id)
        )
        """,
        """
        CREATE TABLE client_mounted_capability_snapshots (
            deployment_namespace TEXT NOT NULL,
            client_session_id UUID NOT NULL,
            snapshot_digest TEXT NOT NULL
                CHECK (snapshot_digest ~ '^[0-9a-f]{64}$'),
            snapshot_json JSONB NOT NULL,
            ui_revision BIGINT NOT NULL CHECK (ui_revision >= 0),
            mounted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (deployment_namespace, client_session_id)
        )
        """,
        """
        CREATE TABLE client_run_bindings (
            deployment_namespace TEXT NOT NULL,
            binding_id UUID NOT NULL,
            task_id UUID NOT NULL,
            run_id TEXT NOT NULL,
            client_session_id UUID NOT NULL,
            profile_digest TEXT NOT NULL
                CHECK (profile_digest ~ '^[0-9a-f]{64}$'),
            mounted_snapshot_digest TEXT NOT NULL
                CHECK (mounted_snapshot_digest ~ '^[0-9a-f]{64}$'),
            task_capability_scope JSONB NOT NULL,
            allowed_actions JSONB NOT NULL,
            binding_revision INTEGER NOT NULL CHECK (binding_revision >= 1),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (deployment_namespace, binding_id),
            UNIQUE (
                deployment_namespace, task_id, run_id, client_session_id
            ),
            CHECK (binding_revision = 1 OR binding_revision > 1)
        )
        """,
        """
        CREATE TABLE client_control_leases (
            deployment_namespace TEXT NOT NULL,
            task_id UUID NOT NULL,
            run_id TEXT NOT NULL,
            run_binding_id UUID,
            client_session_id UUID NOT NULL,
            role TEXT NOT NULL DEFAULT 'controller'
                CHECK (role IN ('controller', 'observer')),
            fence_hash TEXT NOT NULL CHECK (fence_hash ~ '^[0-9a-f]{64}$'),
            acquired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL,
            released_at TIMESTAMPTZ,
            PRIMARY KEY (deployment_namespace, task_id, run_id)
        )
        """,
    ),
)
