"""PostgreSQL v12 schema for the native Memory Gateway authority."""

from agent_storage.postgres.migration_types import Migration

NATIVE_MEMORY_MIGRATION = Migration(
    version=12,
    name="native_memory_gateway",
    statements=(
        """
        CREATE TABLE native_memory_scopes (
            deployment_namespace TEXT NOT NULL,
            scope_id TEXT NOT NULL CHECK (
                scope_id = btrim(scope_id) AND length(scope_id) BETWEEN 1 AND 255
            ),
            current_generation BIGINT NOT NULL CHECK (current_generation >= 1),
            created_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (deployment_namespace, scope_id),
            CHECK (created_at <= updated_at)
        )
        """,
        """
        CREATE TABLE native_memory_operations (
            deployment_namespace TEXT NOT NULL,
            operation_id TEXT NOT NULL CHECK (
                operation_id = btrim(operation_id)
                AND length(operation_id) BETWEEN 1 AND 256
            ),
            scope_id TEXT NOT NULL,
            generation BIGINT NOT NULL CHECK (generation >= 1),
            memory_id UUID NOT NULL,
            operation TEXT NOT NULL CHECK (operation IN ('publish', 'delete')),
            result_status TEXT NOT NULL CHECK (result_status IN ('committed', 'not_found')),
            committed_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (deployment_namespace, operation_id),
            FOREIGN KEY (deployment_namespace, scope_id)
                REFERENCES native_memory_scopes (deployment_namespace, scope_id)
        )
        """,
        """
        CREATE INDEX native_memory_operations_memory
        ON native_memory_operations (
            deployment_namespace, scope_id, memory_id, committed_at
        )
        """,
        """
        CREATE TABLE native_memory_authority (
            deployment_namespace TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            generation BIGINT NOT NULL CHECK (generation >= 1),
            memory_id UUID NOT NULL,
            operation_id TEXT NOT NULL,
            content TEXT NOT NULL CHECK (length(btrim(content)) > 0),
            memory_type TEXT NOT NULL CHECK (length(btrim(memory_type)) > 0),
            topic TEXT NOT NULL CHECK (length(btrim(topic)) > 0),
            status TEXT NOT NULL CHECK (status IN ('confirmed', 'deleted')),
            deleted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (deployment_namespace, memory_id),
            UNIQUE (deployment_namespace, operation_id),
            FOREIGN KEY (deployment_namespace, scope_id)
                REFERENCES native_memory_scopes (deployment_namespace, scope_id),
            FOREIGN KEY (deployment_namespace, operation_id)
                REFERENCES native_memory_operations (deployment_namespace, operation_id),
            CHECK ((status = 'deleted') = (deleted_at IS NOT NULL)),
            CHECK (created_at <= updated_at)
        )
        """,
        """
        CREATE TABLE native_memory_retrieval (
            deployment_namespace TEXT NOT NULL,
            memory_id UUID NOT NULL,
            scope_id TEXT NOT NULL,
            generation BIGINT NOT NULL CHECK (generation >= 1),
            document TSVECTOR NOT NULL,
            PRIMARY KEY (deployment_namespace, memory_id),
            FOREIGN KEY (deployment_namespace, memory_id)
                REFERENCES native_memory_authority (deployment_namespace, memory_id)
                ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX native_memory_retrieval_document
        ON native_memory_retrieval USING GIN (document)
        """,
        """
        CREATE INDEX native_memory_authority_recall
        ON native_memory_authority (
            deployment_namespace, scope_id, generation, status, memory_id
        )
        """,
    ),
)
