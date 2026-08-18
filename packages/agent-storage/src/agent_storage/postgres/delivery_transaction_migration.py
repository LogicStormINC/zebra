"""PostgreSQL v15 schema for cloud delivery transaction ownership."""

from agent_storage.postgres.migration_types import Migration

DELIVERY_TRANSACTION_MIGRATION = Migration(
    version=15,
    name="cloud_delivery_transactions",
    statements=(
        """
        CREATE TABLE delivery_transactions (
            deployment_namespace TEXT NOT NULL
                CHECK (length(btrim(deployment_namespace)) > 0),
            id UUID NOT NULL,
            action TEXT NOT NULL CHECK (length(btrim(action)) > 0),
            idempotency_key TEXT NOT NULL
                CHECK (length(btrim(idempotency_key)) > 0),
            request_hash TEXT NOT NULL CHECK (length(btrim(request_hash)) > 0),
            state TEXT NOT NULL CHECK (state IN (
                'claimed', 'processing', 'committed', 'failed', 'unknown'
            )),
            owner_id TEXT NOT NULL CHECK (length(btrim(owner_id)) > 0),
            claim_token TEXT NOT NULL CHECK (length(btrim(claim_token)) > 0),
            attempt INTEGER NOT NULL CHECK (attempt >= 1),
            receipt_id TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            committed_at TIMESTAMPTZ,
            PRIMARY KEY (id),
            UNIQUE (deployment_namespace, action, idempotency_key),
            CHECK (updated_at >= created_at),
            CHECK (receipt_id IS NULL OR length(btrim(receipt_id)) > 0),
            CHECK ((state = 'committed') = (
                receipt_id IS NOT NULL AND committed_at IS NOT NULL
            )),
            CHECK (state <> 'committed' OR committed_at >= created_at)
        )
        """,
        """
        CREATE INDEX delivery_transactions_recovery
        ON delivery_transactions (deployment_namespace, state, updated_at, id)
        WHERE state IN ('claimed', 'processing', 'unknown', 'failed')
        """,
    ),
)
