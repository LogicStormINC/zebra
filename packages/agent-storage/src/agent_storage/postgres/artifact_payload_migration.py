"""PostgreSQL v9 schema for fenced cloud Artifact payload lifecycle metadata."""

from agent_storage.postgres.migration_types import Migration

ARTIFACT_PAYLOAD_MIGRATION = Migration(
    version=9,
    name="fenced_artifact_payload_lifecycle",
    statements=(
        """
        CREATE TABLE artifact_payload_metadata (
            deployment_namespace TEXT NOT NULL,
            artifact_id UUID NOT NULL,
            session_id UUID NOT NULL,
            intended_event_sequence BIGINT NOT NULL
                CHECK (intended_event_sequence >= 0),
            expected_stream_revision BIGINT NOT NULL
                CHECK (expected_stream_revision >= -1),
            kind TEXT NOT NULL CHECK (
                length(kind) BETWEEN 1 AND 255 AND kind = btrim(kind)
            ),
            mime_type TEXT NOT NULL CHECK (
                length(mime_type) BETWEEN 1 AND 255 AND mime_type = btrim(mime_type)
            ),
            sha256 TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
            idempotency_key TEXT NOT NULL
                CHECK (length(idempotency_key) BETWEEN 1 AND 255
                    AND idempotency_key = btrim(idempotency_key)),
            idempotency_key_hash TEXT NOT NULL
                CHECK (idempotency_key_hash ~ '^[0-9a-f]{64}$'),
            request_hash TEXT NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
            file_name TEXT CHECK (file_name IS NULL OR (
                length(file_name) BETWEEN 1 AND 1024 AND file_name = btrim(file_name)
            )),
            retained_until TIMESTAMPTZ,
            reservation_epoch UUID NOT NULL,
            reservation_fencing_token BIGINT NOT NULL
                CHECK (reservation_fencing_token >= 1),
            reservation_owner_instance_id TEXT NOT NULL
                CHECK (length(reservation_owner_instance_id) BETWEEN 1 AND 255
                    AND reservation_owner_instance_id = btrim(reservation_owner_instance_id)),
            lifecycle_status TEXT NOT NULL CHECK (
                lifecycle_status IN (
                    'staged', 'finalized', 'compensated', 'pruning', 'pruned'
                )
            ),
            lifecycle_revision BIGINT NOT NULL CHECK (lifecycle_revision >= 0),
            object_version TEXT CHECK (object_version IS NULL OR (
                length(object_version) BETWEEN 1 AND 1024
                AND object_version = btrim(object_version)
            )),
            object_verified_at TIMESTAMPTZ,
            event_id UUID,
            event_sequence BIGINT CHECK (event_sequence >= 0),
            artifact_uri TEXT CHECK (artifact_uri IS NULL OR length(artifact_uri) <= 2048),
            finalized_at TIMESTAMPTZ,
            compensated_at TIMESTAMPTZ,
            pruning_at TIMESTAMPTZ,
            pruned_at TIMESTAMPTZ,
            request_created_at TIMESTAMPTZ NOT NULL,
            reserved_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (deployment_namespace, artifact_id),
            UNIQUE (deployment_namespace, session_id, idempotency_key_hash),
            UNIQUE (deployment_namespace, event_id),
            FOREIGN KEY (deployment_namespace, session_id)
                REFERENCES session_streams (deployment_namespace, session_id),
            FOREIGN KEY (
                deployment_namespace, session_id, event_sequence, event_id
            ) REFERENCES session_events (
                deployment_namespace, session_id, sequence, event_id
            )
                DEFERRABLE INITIALLY DEFERRED,
            CHECK (reserved_at <= updated_at),
            CHECK (retained_until IS NULL OR retained_until >= request_created_at),
            CHECK (intended_event_sequence = expected_stream_revision + 1),
            CHECK ((object_version IS NULL) = (object_verified_at IS NULL)),
            CHECK ((event_id IS NULL) = (event_sequence IS NULL)),
            CHECK ((event_id IS NULL) = (artifact_uri IS NULL)),
            CHECK (event_sequence IS NULL OR event_sequence = intended_event_sequence),
            CHECK (artifact_uri IS NULL OR artifact_uri = 'artifact://' || artifact_id::text),
            CHECK (finalized_at IS NULL OR finalized_at >= reserved_at),
            CHECK (compensated_at IS NULL OR compensated_at >= reserved_at),
            CHECK (pruning_at IS NULL OR pruning_at >= finalized_at),
            CHECK (pruned_at IS NULL OR pruned_at >= pruning_at),
            CHECK (
                (lifecycle_status = 'staged'
                    AND event_id IS NULL AND finalized_at IS NULL
                    AND compensated_at IS NULL AND pruning_at IS NULL
                    AND pruned_at IS NULL)
                OR (lifecycle_status = 'compensated'
                    AND event_id IS NULL AND finalized_at IS NULL
                    AND compensated_at IS NOT NULL AND pruning_at IS NULL
                    AND pruned_at IS NULL)
                OR (lifecycle_status = 'finalized'
                    AND event_id IS NOT NULL AND object_version IS NOT NULL
                    AND finalized_at IS NOT NULL AND compensated_at IS NULL
                    AND pruning_at IS NULL AND pruned_at IS NULL)
                OR (lifecycle_status = 'pruning'
                    AND event_id IS NOT NULL AND object_version IS NOT NULL
                    AND finalized_at IS NOT NULL AND compensated_at IS NULL
                    AND pruning_at IS NOT NULL AND pruned_at IS NULL)
                OR (lifecycle_status = 'pruned'
                    AND event_id IS NOT NULL AND object_version IS NOT NULL
                    AND finalized_at IS NOT NULL AND compensated_at IS NULL
                    AND pruning_at IS NOT NULL AND pruned_at IS NOT NULL)
            )
        )
        """,
        """
        CREATE INDEX artifact_payload_reconcile
        ON artifact_payload_metadata (
            deployment_namespace, session_id, lifecycle_status, updated_at, artifact_id
        ) WHERE lifecycle_status IN ('staged', 'pruning')
        """,
        """
        CREATE INDEX artifact_payload_retention
        ON artifact_payload_metadata (
            deployment_namespace, session_id, retained_until, artifact_id
        ) WHERE lifecycle_status = 'finalized' AND retained_until IS NOT NULL
        """,
        """
        CREATE TABLE artifact_payload_mutations (
            deployment_namespace TEXT NOT NULL,
            artifact_id UUID NOT NULL,
            operation_kind TEXT NOT NULL CHECK (operation_kind IN (
                'record_object', 'finalize', 'compensate',
                'begin_prune', 'complete_prune'
            )),
            idempotency_key_hash TEXT NOT NULL
                CHECK (idempotency_key_hash ~ '^[0-9a-f]{64}$'),
            request_hash TEXT NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
            resulting_revision BIGINT NOT NULL CHECK (resulting_revision >= 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (
                deployment_namespace, artifact_id, operation_kind, idempotency_key_hash
            ),
            UNIQUE (deployment_namespace, artifact_id, resulting_revision),
            FOREIGN KEY (deployment_namespace, artifact_id)
                REFERENCES artifact_payload_metadata (deployment_namespace, artifact_id)
        )
        """,
        """
        CREATE TABLE artifact_payload_management_audit (
            deployment_namespace TEXT NOT NULL,
            operation_id UUID NOT NULL,
            artifact_id UUID NOT NULL,
            operation_kind TEXT NOT NULL CHECK (operation_kind IN (
                'finalize', 'compensate', 'begin_prune', 'complete_prune'
            )),
            operator_id TEXT NOT NULL CHECK (
                length(operator_id) BETWEEN 1 AND 255 AND operator_id = btrim(operator_id)
            ),
            reason TEXT NOT NULL CHECK (
                length(reason) BETWEEN 1 AND 1024 AND reason = btrim(reason)
            ),
            expected_stream_revision BIGINT NOT NULL
                CHECK (expected_stream_revision >= -1),
            resulting_lifecycle_revision BIGINT NOT NULL
                CHECK (resulting_lifecycle_revision >= 0),
            from_status TEXT NOT NULL,
            to_status TEXT NOT NULL,
            request_hash TEXT NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (deployment_namespace, operation_id),
            FOREIGN KEY (deployment_namespace, artifact_id)
                REFERENCES artifact_payload_metadata (deployment_namespace, artifact_id),
            CHECK (from_status IN (
                'staged', 'finalized', 'compensated', 'pruning', 'pruned'
            )),
            CHECK (to_status IN (
                'staged', 'finalized', 'compensated', 'pruning', 'pruned'
            ))
        )
        """,
    ),
)
