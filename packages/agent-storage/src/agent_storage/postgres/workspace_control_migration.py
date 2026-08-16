"""PostgreSQL v18 schema for the Cloud Workspace Control Plane authority."""

from agent_storage.postgres.migration_types import Migration

WORKSPACE_CONTROL_MIGRATION = Migration(
    version=18,
    name="workspace_control_instances_operations_snapshots",
    statements=(
        """
        CREATE TABLE workspace_control_instances (
            deployment_namespace TEXT NOT NULL CHECK (
                length(btrim(deployment_namespace)) BETWEEN 1 AND 255
            ),
            workspace_id UUID NOT NULL,
            source_kind TEXT NOT NULL CHECK (
                source_kind IN (
                    'git_repository',
                    'uploaded_archive',
                    'durable_snapshot',
                    'host_reference'
                )
            ),
            source_locator TEXT NOT NULL CHECK (
                length(btrim(source_locator)) BETWEEN 1 AND 2048
            ),
            source_pinned_revision TEXT CHECK (
                source_pinned_revision IS NULL
                OR length(btrim(source_pinned_revision)) BETWEEN 1 AND 255
            ),
            source_archive_uri TEXT CHECK (
                source_archive_uri IS NULL
                OR length(btrim(source_archive_uri)) BETWEEN 1 AND 2048
            ),
            source_content_digest TEXT CHECK (
                source_content_digest IS NULL OR length(source_content_digest) = 64
            ),
            state TEXT NOT NULL CHECK (
                state IN (
                    'pending',
                    'provisioning',
                    'ready',
                    'sealed',
                    'released',
                    'failed',
                    'uncertain'
                )
            ),
            materialized_revision TEXT CHECK (
                materialized_revision IS NULL
                OR length(btrim(materialized_revision)) BETWEEN 1 AND 255
            ),
            content_digest TEXT CHECK (content_digest IS NULL OR length(content_digest) = 64),
            volume_ref TEXT CHECK (
                volume_ref IS NULL OR length(btrim(volume_ref)) BETWEEN 1 AND 1024
            ),
            owner_session_id UUID,
            quota_bytes BIGINT NOT NULL CHECK (quota_bytes > 0),
            provision_operation_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (deployment_namespace, workspace_id),
            CHECK (created_at <= updated_at),
            CHECK (
                state NOT IN ('ready', 'sealed')
                OR (
                    materialized_revision IS NOT NULL
                    AND content_digest IS NOT NULL
                )
            )
        )
        """,
        """
        CREATE INDEX workspace_control_instances_state
        ON workspace_control_instances (deployment_namespace, state, created_at)
        """,
        """
        CREATE INDEX workspace_control_instances_uncertain
        ON workspace_control_instances (deployment_namespace, updated_at)
        WHERE state = 'uncertain'
        """,
        """
        CREATE TABLE workspace_control_operations (
            deployment_namespace TEXT NOT NULL,
            operation_id UUID NOT NULL,
            workspace_id UUID NOT NULL,
            action TEXT NOT NULL CHECK (length(btrim(action)) BETWEEN 1 AND 64),
            idempotency_key TEXT NOT NULL CHECK (
                length(btrim(idempotency_key)) BETWEEN 1 AND 255
            ),
            resulting_state TEXT NOT NULL,
            idempotent_replay BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (deployment_namespace, operation_id),
            UNIQUE (deployment_namespace, idempotency_key),
            FOREIGN KEY (deployment_namespace, workspace_id)
                REFERENCES workspace_control_instances (deployment_namespace, workspace_id)
        )
        """,
        """
        CREATE TABLE workspace_control_snapshots (
            deployment_namespace TEXT NOT NULL,
            snapshot_id UUID NOT NULL,
            workspace_id UUID NOT NULL,
            materialized_revision TEXT NOT NULL CHECK (
                length(btrim(materialized_revision)) BETWEEN 1 AND 255
            ),
            content_digest TEXT NOT NULL CHECK (length(content_digest) = 64),
            object_uri TEXT NOT NULL CHECK (
                length(btrim(object_uri)) BETWEEN 1 AND 2048
            ),
            created_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (deployment_namespace, snapshot_id),
            FOREIGN KEY (deployment_namespace, workspace_id)
                REFERENCES workspace_control_instances (deployment_namespace, workspace_id)
        )
        """,
        """
        CREATE INDEX workspace_control_snapshots_workspace
        ON workspace_control_snapshots (deployment_namespace, workspace_id, created_at)
        """,
    ),
)
