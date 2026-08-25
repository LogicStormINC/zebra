"""Migration v33: durable client effects, receipts and continuations."""

from agent_storage.postgres.migration_types import Migration

CLIENT_EFFECT_MIGRATION = Migration(
    version=33,
    name="client_effects",
    statements=(
        """
        CREATE TABLE client_effects (
            deployment_namespace TEXT NOT NULL,
            effect_id UUID NOT NULL,
            task_id UUID NOT NULL,
            run_id TEXT NOT NULL,
            client_session_id UUID NOT NULL,
            tool_call_id UUID NOT NULL,
            action_name TEXT NOT NULL,
            arguments_json JSONB NOT NULL,
            action_contract_digest TEXT NOT NULL
                CHECK (action_contract_digest ~ '^[0-9a-f]{64}$'),
            client_binding_digest TEXT NOT NULL
                CHECK (client_binding_digest ~ '^[0-9a-f]{64}$'),
            fence_hash TEXT NOT NULL CHECK (fence_hash ~ '^[0-9a-f]{64}$'),
            expected_ui_revision BIGINT NOT NULL CHECK (expected_ui_revision >= 0),
            idempotency_key TEXT NOT NULL,
            request_digest TEXT NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN (
                    'pending', 'delivered', 'succeeded', 'failed', 'declined',
                    'unavailable', 'stale_ui_state', 'expired', 'uncertain',
                    'cancelled'
                )),
            requested_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (deployment_namespace, effect_id),
            UNIQUE (deployment_namespace, idempotency_key)
        )
        """,
        """
        CREATE INDEX client_effects_pending_idx
            ON client_effects (deployment_namespace, client_session_id, requested_at)
            WHERE status = 'pending'
        """,
        """
        CREATE TABLE client_effect_receipts (
            deployment_namespace TEXT NOT NULL,
            effect_id UUID NOT NULL,
            receipt_id UUID NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_digest TEXT NOT NULL
                CHECK (request_digest ~ '^[0-9a-f]{64}$'),
            status TEXT NOT NULL
                CHECK (status IN (
                    'succeeded', 'failed', 'declined', 'unavailable',
                    'stale_ui_state'
                )),
            result_json JSONB NOT NULL,
            received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (deployment_namespace, effect_id),
            UNIQUE (deployment_namespace, receipt_id)
        )
        """,
        """
        CREATE TABLE client_effect_continuations (
            deployment_namespace TEXT NOT NULL,
            effect_id UUID NOT NULL,
            task_id UUID NOT NULL,
            run_id TEXT NOT NULL,
            tool_call_id UUID NOT NULL,
            action_name TEXT NOT NULL,
            assistant_message TEXT NOT NULL DEFAULT '',
            model_calls_used INTEGER NOT NULL DEFAULT 0,
            tool_calls_executed INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (deployment_namespace, effect_id)
        )
        """,
    ),
)
