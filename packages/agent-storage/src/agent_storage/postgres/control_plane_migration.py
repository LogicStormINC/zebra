"""PostgreSQL v14 schema for shared cloud control-plane records."""

from agent_storage.postgres.migration_types import Migration

CONTROL_PLANE_MIGRATION = Migration(
    version=14,
    name="cloud_control_plane_shared_records",
    statements=(
        """
        CREATE TABLE control_plane_idempotency_records (
            deployment_namespace TEXT NOT NULL,
            action TEXT NOT NULL CHECK (length(btrim(action)) > 0),
            idempotency_key TEXT NOT NULL CHECK (length(btrim(idempotency_key)) > 0),
            request_hash TEXT NOT NULL CHECK (length(btrim(request_hash)) > 0),
            status_code INTEGER NOT NULL CHECK (status_code BETWEEN 100 AND 599),
            response_body JSONB NOT NULL CHECK (jsonb_typeof(response_body) = 'object'),
            created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (deployment_namespace, action, idempotency_key)
        )
        """,
        """
        CREATE TABLE control_plane_delivery_audit_records (
            deployment_namespace TEXT NOT NULL,
            audit_id BIGINT GENERATED ALWAYS AS IDENTITY,
            session_id UUID NOT NULL,
            action TEXT NOT NULL CHECK (length(btrim(action)) > 0),
            status TEXT NOT NULL CHECK (length(btrim(status)) > 0),
            status_code INTEGER NOT NULL CHECK (status_code BETWEEN 100 AND 599),
            policy_profile TEXT,
            idempotency_key TEXT,
            result_metadata JSONB NOT NULL
                CHECK (jsonb_typeof(result_metadata) = 'object'),
            created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (deployment_namespace, audit_id),
            CHECK (policy_profile IS NULL OR length(btrim(policy_profile)) > 0),
            CHECK (idempotency_key IS NULL OR length(btrim(idempotency_key)) > 0)
        )
        """,
        """
        CREATE INDEX control_plane_delivery_audit_session
        ON control_plane_delivery_audit_records (
            deployment_namespace, session_id, audit_id
        )
        """,
    ),
)
