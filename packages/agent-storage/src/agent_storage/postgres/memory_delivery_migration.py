"""PostgreSQL v11 schema for metadata-only derived Memory delivery."""

from agent_storage.postgres.migration_types import Migration

MEMORY_DELIVERY_MIGRATION = Migration(
    version=11,
    name="memory_delivery_ledger",
    statements=(
        """
        CREATE TABLE memory_delivery_scopes (
            deployment_namespace TEXT NOT NULL,
            scope_digest TEXT NOT NULL CHECK (scope_digest ~ '^[0-9a-f]{64}$'),
            generation BIGINT NOT NULL CHECK (generation >= 1),
            state TEXT NOT NULL CHECK (state IN ('active', 'quarantined', 'rebuilding')),
            revision BIGINT NOT NULL CHECK (revision >= 0),
            reason_code TEXT,
            operator TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (deployment_namespace, scope_digest, generation),
            CHECK (reason_code IS NULL OR (
                reason_code = btrim(reason_code) AND length(reason_code) <= 128
            )),
            CHECK (operator IS NULL OR (
                operator = btrim(operator) AND length(operator) <= 255
            )),
            CHECK (created_at <= updated_at)
        )
        """,
        """
        CREATE UNIQUE INDEX memory_delivery_one_active_generation
        ON memory_delivery_scopes (deployment_namespace, scope_digest)
        WHERE state = 'active'
        """,
        """
        CREATE TABLE memory_delivery_operations (
            deployment_namespace TEXT NOT NULL,
            delivery_operation_id UUID NOT NULL,
            memory_id UUID NOT NULL,
            scope_digest TEXT NOT NULL,
            generation BIGINT NOT NULL CHECK (generation >= 1),
            memory_revision BIGINT NOT NULL CHECK (memory_revision >= 1),
            content_digest TEXT NOT NULL CHECK (content_digest ~ '^[0-9a-f]{64}$'),
            operation TEXT NOT NULL CHECK (operation IN ('publish', 'delete')),
            idempotency_key TEXT NOT NULL CHECK (
                idempotency_key = btrim(idempotency_key)
                AND length(idempotency_key) BETWEEN 1 AND 256
            ),
            state TEXT NOT NULL CHECK (state IN (
                'pending', 'claimed', 'in_flight', 'completed', 'uncertain', 'dead_letter'
            )),
            attempt INTEGER NOT NULL CHECK (attempt >= 0),
            next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            claim_token TEXT,
            claim_owner TEXT,
            claim_expires_at TIMESTAMPTZ,
            certainty TEXT CHECK (certainty IS NULL OR certainty IN (
                'applied', 'definite_no_effect', 'unknown'
            )),
            provider_ref TEXT,
            error_code TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            completed_at TIMESTAMPTZ,
            PRIMARY KEY (deployment_namespace, delivery_operation_id),
            UNIQUE (deployment_namespace, idempotency_key),
            FOREIGN KEY (deployment_namespace, scope_digest, generation)
                REFERENCES memory_delivery_scopes
                (deployment_namespace, scope_digest, generation),
            CHECK ((state IN ('claimed', 'in_flight')) = (
                claim_token IS NOT NULL
                AND claim_owner IS NOT NULL
                AND claim_expires_at IS NOT NULL
            )),
            CHECK (
                (state IN ('pending', 'claimed') AND (
                    certainty IS NULL OR certainty = 'definite_no_effect'
                ))
                OR (state = 'in_flight' AND certainty IS NULL)
                OR (state = 'completed' AND certainty IN ('applied', 'definite_no_effect'))
                OR (state = 'uncertain' AND certainty = 'unknown')
                OR (state = 'dead_letter' AND certainty = 'definite_no_effect')
            ),
            CHECK (provider_ref IS NULL OR (
                provider_ref = btrim(provider_ref) AND length(provider_ref) <= 512
            )),
            CHECK (error_code IS NULL OR (
                error_code = btrim(error_code) AND length(error_code) <= 128
            )),
            CHECK (state != 'completed' OR operation != 'publish'
                OR certainty != 'applied' OR provider_ref IS NOT NULL),
            CHECK (state = 'completed' OR completed_at IS NULL),
            CHECK (created_at <= updated_at)
        )
        """,
        """
        CREATE INDEX memory_delivery_pending_claims
        ON memory_delivery_operations (
            deployment_namespace, scope_digest, generation,
            next_attempt_at, created_at, delivery_operation_id
        )
        WHERE state = 'pending'
        """,
        """
        CREATE INDEX memory_delivery_expired_claims
        ON memory_delivery_operations (
            deployment_namespace, claim_expires_at, delivery_operation_id
        )
        WHERE state = 'claimed'
        """,
        """
        CREATE TABLE memory_provider_mappings (
            deployment_namespace TEXT NOT NULL,
            scope_digest TEXT NOT NULL,
            generation BIGINT NOT NULL CHECK (generation >= 1),
            memory_id UUID NOT NULL,
            provider_ref TEXT NOT NULL CHECK (
                provider_ref = btrim(provider_ref) AND length(provider_ref) <= 512
            ),
            memory_revision BIGINT NOT NULL CHECK (memory_revision >= 1),
            content_digest TEXT NOT NULL CHECK (content_digest ~ '^[0-9a-f]{64}$'),
            created_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (deployment_namespace, scope_digest, generation, memory_id),
            UNIQUE (deployment_namespace, scope_digest, generation, provider_ref),
            FOREIGN KEY (deployment_namespace, scope_digest, generation)
                REFERENCES memory_delivery_scopes
                (deployment_namespace, scope_digest, generation),
            CHECK (created_at <= updated_at)
        )
        """,
        """
        CREATE INDEX memory_provider_mappings_memory
        ON memory_provider_mappings (
            deployment_namespace, memory_id, scope_digest, generation
        )
        """,
    ),
)
