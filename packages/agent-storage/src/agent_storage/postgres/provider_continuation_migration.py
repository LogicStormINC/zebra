"""PostgreSQL v13 schema for fenced Provider Continuation authority."""

from agent_storage.postgres.migration_types import Migration

PROVIDER_CONTINUATION_MIGRATION = Migration(
    version=13,
    name="fenced_provider_continuation_authority",
    statements=(
        """
        CREATE TABLE provider_continuation_artifacts (
            deployment_namespace TEXT NOT NULL,
            continuation_id TEXT NOT NULL CHECK (length(btrim(continuation_id)) > 0),
            authority_issuer TEXT NOT NULL
                CHECK (length(btrim(authority_issuer)) > 0),
            namespace_id TEXT NOT NULL CHECK (length(btrim(namespace_id)) > 0),
            session_id UUID NOT NULL,
            reference_id TEXT NOT NULL CHECK (length(btrim(reference_id)) > 0),
            provider TEXT NOT NULL CHECK (length(btrim(provider)) > 0),
            model_name TEXT NOT NULL CHECK (length(btrim(model_name)) > 0),
            capability_version TEXT NOT NULL
                CHECK (length(btrim(capability_version)) > 0),
            source_hash TEXT NOT NULL CHECK (length(btrim(source_hash)) > 0),
            opaque_payload BYTEA,
            payload_sha256 TEXT NOT NULL CHECK (length(payload_sha256) = 64),
            size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
            created_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            deleted_at TIMESTAMPTZ,
            lifecycle_revision BIGINT NOT NULL DEFAULT 0
                CHECK (lifecycle_revision >= 0),
            selection_event_id UUID,
            selection_event_sequence BIGINT,
            idempotency_key TEXT NOT NULL CHECK (length(btrim(idempotency_key)) > 0),
            request_hash TEXT NOT NULL CHECK (length(request_hash) = 64),
            accepted_lease_epoch UUID NOT NULL,
            accepted_lease_fencing_token BIGINT NOT NULL
                CHECK (accepted_lease_fencing_token >= 1),
            accepted_lease_owner_instance_id TEXT NOT NULL
                CHECK (length(btrim(accepted_lease_owner_instance_id)) > 0),
            PRIMARY KEY (deployment_namespace, continuation_id),
            UNIQUE (authority_issuer, namespace_id, continuation_id),
            UNIQUE (deployment_namespace, provider, reference_id),
            UNIQUE (deployment_namespace, session_id, idempotency_key),
            FOREIGN KEY (deployment_namespace, session_id)
                REFERENCES session_streams (deployment_namespace, session_id),
            FOREIGN KEY (deployment_namespace, session_id, selection_event_sequence,
                         selection_event_id)
                REFERENCES session_events (
                    deployment_namespace, session_id, sequence, event_id
                ) DEFERRABLE INITIALLY DEFERRED,
            CHECK ((selection_event_id IS NULL) = (selection_event_sequence IS NULL)),
            CHECK (deleted_at IS NULL OR opaque_payload IS NULL),
            CHECK (created_at < expires_at),
            CHECK (deleted_at IS NULL OR deleted_at >= created_at)
        )
        """,
        """
        CREATE INDEX provider_continuation_expiry
        ON provider_continuation_artifacts (
            deployment_namespace, expires_at, continuation_id
        )
        WHERE deleted_at IS NULL
        """,
        """
        CREATE INDEX provider_continuation_session
        ON provider_continuation_artifacts (
            deployment_namespace, session_id, continuation_id
        )
        """,
        """
        CREATE TABLE provider_continuation_mutations (
            deployment_namespace TEXT NOT NULL,
            continuation_id TEXT NOT NULL,
            operation_kind TEXT NOT NULL CHECK (length(btrim(operation_kind)) > 0),
            idempotency_key TEXT NOT NULL CHECK (length(btrim(idempotency_key)) > 0),
            request_hash TEXT NOT NULL CHECK (length(request_hash) = 64),
            resulting_revision BIGINT NOT NULL CHECK (resulting_revision >= 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (
                deployment_namespace, continuation_id, operation_kind, idempotency_key
            ),
            FOREIGN KEY (deployment_namespace, continuation_id)
                REFERENCES provider_continuation_artifacts (
                    deployment_namespace, continuation_id
                )
        )
        """,
        """
        CREATE TABLE provider_continuation_management_audit (
            operation_id UUID PRIMARY KEY,
            deployment_namespace TEXT NOT NULL,
            authority_issuer TEXT NOT NULL,
            namespace_id TEXT NOT NULL,
            operator_id TEXT NOT NULL CHECK (length(btrim(operator_id)) > 0),
            reason TEXT NOT NULL CHECK (length(btrim(reason)) > 0),
            request_hash TEXT NOT NULL CHECK (length(request_hash) = 64),
            expired_continuation_ids JSONB NOT NULL
                CHECK (jsonb_typeof(expired_continuation_ids) = 'array'),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            UNIQUE (deployment_namespace, operation_id)
        )
        """,
    ),
)
