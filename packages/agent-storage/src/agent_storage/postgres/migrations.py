"""Immutable PostgreSQL migration catalog."""

from agent_storage.postgres.agent_registry_migration import (
    AGENT_REGISTRY_MIGRATION,
)
from agent_storage.postgres.agent_release_enforcement_migration import (
    AGENT_RELEASE_ENFORCEMENT_MIGRATION,
)
from agent_storage.postgres.artifact_payload_migration import ARTIFACT_PAYLOAD_MIGRATION
from agent_storage.postgres.control_plane_migration import CONTROL_PLANE_MIGRATION
from agent_storage.postgres.delivery_transaction_migration import (
    DELIVERY_TRANSACTION_MIGRATION,
)
from agent_storage.postgres.governed_memory_migration import GOVERNED_MEMORY_MIGRATION
from agent_storage.postgres.governed_memory_scope_migration import (
    GOVERNED_MEMORY_SCOPE_MIGRATION,
)
from agent_storage.postgres.handoff_migration import HANDOFF_MIGRATION
from agent_storage.postgres.host_auth_migration import HOST_AUTH_MIGRATION
from agent_storage.postgres.host_connector_migration import HOST_CONNECTOR_MIGRATION
from agent_storage.postgres.memory_delivery_migration import MEMORY_DELIVERY_MIGRATION
from agent_storage.postgres.migration_recovery_migration import MIGRATION_RECOVERY_MIGRATION
from agent_storage.postgres.migration_types import Migration
from agent_storage.postgres.native_memory_migration import NATIVE_MEMORY_MIGRATION
from agent_storage.postgres.provider_continuation_migration import (
    PROVIDER_CONTINUATION_MIGRATION,
)
from agent_storage.postgres.session_tenant_migration import (
    SESSION_TENANT_NAMESPACE_MIGRATION,
)
from agent_storage.postgres.workspace_control_migration import WORKSPACE_CONTROL_MIGRATION
from agent_storage.postgres.workspace_definition_snapshot_migration import (
    WORKSPACE_DEFINITION_SNAPSHOT_MIGRATION,
)

MIGRATIONS = (
    Migration(
        version=1,
        name="event_and_projection_storage",
        statements=(
            """
            CREATE TABLE session_streams (
                deployment_namespace TEXT NOT NULL,
                session_id UUID NOT NULL,
                current_version BIGINT NOT NULL CHECK (current_version >= 0),
                PRIMARY KEY (deployment_namespace, session_id)
            )
            """,
            """
            CREATE TABLE session_events (
                deployment_namespace TEXT NOT NULL,
                event_id UUID NOT NULL,
                session_id UUID NOT NULL,
                sequence BIGINT NOT NULL CHECK (sequence >= 0),
                event_type TEXT NOT NULL,
                payload JSONB NOT NULL,
                actor TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                causation_id UUID,
                correlation_id UUID,
                idempotency_key TEXT,
                policy_version TEXT,
                model_profile TEXT,
                PRIMARY KEY (deployment_namespace, event_id),
                UNIQUE (deployment_namespace, session_id, sequence),
                FOREIGN KEY (deployment_namespace, session_id)
                    REFERENCES session_streams (deployment_namespace, session_id)
            )
            """,
            """
            CREATE UNIQUE INDEX session_events_idempotency
            ON session_events (deployment_namespace, session_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL
            """,
            """
            CREATE INDEX session_events_stream_order
            ON session_events (deployment_namespace, session_id, sequence)
            """,
            """
            CREATE TABLE session_projections (
                deployment_namespace TEXT NOT NULL,
                session_id UUID NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                current_sequence BIGINT NOT NULL CHECK (current_sequence >= 0),
                approval_context_json JSONB,
                clarification_context_json JSONB,
                task_plan_json JSONB,
                PRIMARY KEY (deployment_namespace, session_id)
            )
            """,
            """
            CREATE INDEX session_projections_recent
            ON session_projections (
                deployment_namespace,
                updated_at DESC,
                created_at DESC,
                session_id
            )
            """,
            """
            CREATE INDEX session_projections_status_order
            ON session_projections (
                deployment_namespace,
                status,
                updated_at,
                created_at,
                session_id
            )
            """,
        ),
    ),
    Migration(
        version=2,
        name="control_plane_epoch_and_leases",
        statements=(
            """
            CREATE TABLE control_plane_epochs (
                deployment_namespace TEXT PRIMARY KEY,
                epoch UUID NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp()
            )
            """,
            """
            CREATE TABLE worker_leases (
                deployment_namespace TEXT NOT NULL,
                session_id UUID NOT NULL,
                control_plane_epoch UUID NOT NULL,
                fencing_token BIGINT NOT NULL CHECK (fencing_token >= 1),
                owner_instance_id TEXT NOT NULL CHECK (length(btrim(owner_instance_id)) > 0),
                checkpoint BIGINT NOT NULL CHECK (checkpoint >= 0),
                acquired_at TIMESTAMPTZ NOT NULL,
                heartbeat_at TIMESTAMPTZ NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                released_at TIMESTAMPTZ,
                PRIMARY KEY (deployment_namespace, session_id),
                FOREIGN KEY (deployment_namespace)
                    REFERENCES control_plane_epochs (deployment_namespace),
                CHECK (acquired_at <= heartbeat_at),
                CHECK (heartbeat_at < expires_at),
                CHECK (released_at IS NULL OR released_at >= acquired_at)
            )
            """,
        ),
    ),
    Migration(
        version=3,
        name="fenced_effect_dispatch_outbox",
        statements=(
            """
            CREATE TABLE effect_outbox (
                deployment_namespace TEXT NOT NULL,
                dispatch_id UUID NOT NULL,
                execution_session_id UUID NOT NULL,
                root_session_id UUID NOT NULL,
                ledger_key TEXT NOT NULL,
                attempt INTEGER NOT NULL CHECK (attempt >= 1),
                retry_key TEXT,
                request_hash TEXT NOT NULL CHECK (length(request_hash) = 64),
                effect_identity JSONB NOT NULL,
                payload_artifact_ref TEXT NOT NULL
                    CHECK (length(btrim(payload_artifact_ref)) > 0),
                status TEXT NOT NULL CHECK (status IN (
                    'pending', 'claimed', 'succeeded', 'failed_no_effect',
                    'uncertain', 'dead_letter'
                )),
                claim_epoch UUID,
                claim_fencing_token BIGINT CHECK (claim_fencing_token >= 1),
                claim_owner_instance_id TEXT,
                claim_expires_at TIMESTAMPTZ,
                intent_event_id UUID NOT NULL,
                terminal_event_id UUID,
                result JSONB,
                evidence JSONB,
                evidence_history JSONB NOT NULL DEFAULT '[]'::jsonb
                    CHECK (jsonb_typeof(evidence_history) = 'array'),
                created_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
                PRIMARY KEY (deployment_namespace, dispatch_id),
                UNIQUE (deployment_namespace, root_session_id, ledger_key, attempt),
                FOREIGN KEY (deployment_namespace, intent_event_id)
                    REFERENCES session_events (deployment_namespace, event_id),
                FOREIGN KEY (deployment_namespace, terminal_event_id)
                    REFERENCES session_events (deployment_namespace, event_id),
                CHECK ((status = 'claimed') = (
                    claim_epoch IS NOT NULL
                    AND claim_fencing_token IS NOT NULL
                    AND claim_owner_instance_id IS NOT NULL
                    AND claim_expires_at IS NOT NULL
                )),
                CHECK (status != 'succeeded' OR result IS NOT NULL),
                CHECK (status = 'succeeded' OR result IS NULL),
                CHECK (status NOT IN ('pending', 'claimed') OR (
                    terminal_event_id IS NULL AND evidence IS NULL
                    AND evidence_history = '[]'::jsonb
                )),
                CHECK (status NOT IN ('succeeded', 'failed_no_effect', 'dead_letter')
                    OR terminal_event_id IS NOT NULL),
                CHECK (status NOT IN ('failed_no_effect', 'uncertain', 'dead_letter')
                    OR (evidence IS NOT NULL AND jsonb_array_length(evidence_history) > 0))
            )
            """,
            """
            CREATE UNIQUE INDEX effect_outbox_retry_key
            ON effect_outbox (deployment_namespace, root_session_id, ledger_key, retry_key)
            WHERE retry_key IS NOT NULL
            """,
            """
            CREATE INDEX effect_outbox_pending_delivery
            ON effect_outbox (
                deployment_namespace, execution_session_id, created_at, dispatch_id
            )
            WHERE status = 'pending'
            """,
            """
            CREATE INDEX effect_outbox_reconciliation
            ON effect_outbox (deployment_namespace, claim_expires_at, dispatch_id)
            WHERE status = 'claimed'
            """,
        ),
    ),
    Migration(
        version=4,
        name="fenced_workspace_projections",
        statements=(
            """
            CREATE TABLE workspace_projections (
                deployment_namespace TEXT NOT NULL,
                session_id UUID NOT NULL,
                workspace_root TEXT NOT NULL CHECK (length(btrim(workspace_root)) > 0),
                prepared_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                current_sequence BIGINT NOT NULL CHECK (current_sequence >= 0),
                status TEXT NOT NULL CHECK (status IN (
                    'prepared', 'running', 'waiting_approval', 'suspended',
                    'completed', 'failed', 'cancelled'
                )),
                policy_profile TEXT,
                tool_profile TEXT NOT NULL CHECK (tool_profile IN ('general', 'coding')),
                network_profile TEXT NOT NULL CHECK (network_profile IN (
                    'none', 'setup-only', 'domain-allowlist', 'mcp-proxy-only',
                    'git-proxy-only', 'full-trusted-local'
                )),
                network_allowlist JSONB NOT NULL DEFAULT '[]'::jsonb
                    CHECK (jsonb_typeof(network_allowlist) = 'array'),
                mcp_allowlist JSONB CHECK (
                    mcp_allowlist IS NULL OR jsonb_typeof(mcp_allowlist) = 'array'
                ),
                skill_components JSONB CHECK (
                    skill_components IS NULL OR jsonb_typeof(skill_components) = 'array'
                ),
                last_attempt_number INTEGER CHECK (last_attempt_number >= 1),
                runtime_name TEXT,
                runtime_engine TEXT,
                runtime_image TEXT,
                runtime_spec_digest TEXT,
                runtime_network_enforcement TEXT,
                runtime_workspace_writable BOOLEAN,
                snapshot_id TEXT,
                snapshot_path TEXT,
                PRIMARY KEY (deployment_namespace, session_id),
                FOREIGN KEY (deployment_namespace, session_id)
                    REFERENCES session_streams (deployment_namespace, session_id),
                CHECK (prepared_at <= updated_at)
            )
            """,
        ),
    ),
    Migration(
        version=5,
        name="task_and_segment_index",
        statements=(
            """
            CREATE TABLE agent_tasks (
                deployment_namespace TEXT NOT NULL,
                task_id UUID NOT NULL,
                root_session_id UUID NOT NULL,
                active_segment_id UUID NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (deployment_namespace, task_id),
                UNIQUE (deployment_namespace, root_session_id),
                FOREIGN KEY (deployment_namespace, root_session_id)
                    REFERENCES session_projections (deployment_namespace, session_id),
                FOREIGN KEY (deployment_namespace, active_segment_id)
                    REFERENCES session_projections (deployment_namespace, session_id),
                CHECK (created_at <= updated_at)
            )
            """,
            """
            CREATE TABLE execution_segments (
                deployment_namespace TEXT NOT NULL,
                session_id UUID NOT NULL,
                task_id UUID NOT NULL,
                predecessor_id UUID,
                segment_index INTEGER NOT NULL CHECK (segment_index >= 0),
                visibility TEXT NOT NULL CHECK (visibility = 'internal'),
                rollover_reason TEXT CHECK (rollover_reason IN (
                    'context_pressure', 'recovery', 'terminal_follow_up', 'agent_hint'
                )),
                PRIMARY KEY (deployment_namespace, session_id),
                UNIQUE (deployment_namespace, task_id, segment_index),
                UNIQUE (deployment_namespace, task_id, session_id),
                FOREIGN KEY (deployment_namespace, task_id)
                    REFERENCES agent_tasks (deployment_namespace, task_id)
                    ON DELETE CASCADE,
                FOREIGN KEY (deployment_namespace, session_id)
                    REFERENCES session_projections (deployment_namespace, session_id),
                FOREIGN KEY (deployment_namespace, task_id, predecessor_id)
                    REFERENCES execution_segments (
                        deployment_namespace, task_id, session_id
                    ) DEFERRABLE INITIALLY DEFERRED,
                CHECK ((segment_index = 0) = (predecessor_id IS NULL))
            )
            """,
            """
            ALTER TABLE agent_tasks
            ADD CONSTRAINT agent_tasks_active_segment_owner
            FOREIGN KEY (deployment_namespace, task_id, active_segment_id)
            REFERENCES execution_segments (deployment_namespace, task_id, session_id)
            DEFERRABLE INITIALLY DEFERRED
            """,
            """
            CREATE INDEX execution_segments_task_order
            ON execution_segments (deployment_namespace, task_id, segment_index)
            """,
            """
            CREATE TABLE task_event_index (
                deployment_namespace TEXT NOT NULL,
                task_id UUID NOT NULL,
                task_sequence BIGINT NOT NULL CHECK (task_sequence >= 0),
                event_id UUID NOT NULL,
                segment_id UUID NOT NULL,
                segment_sequence BIGINT NOT NULL CHECK (segment_sequence >= 0),
                PRIMARY KEY (deployment_namespace, task_id, task_sequence),
                UNIQUE (deployment_namespace, event_id),
                UNIQUE (
                    deployment_namespace, task_id, segment_id, segment_sequence
                ),
                FOREIGN KEY (deployment_namespace, task_id)
                    REFERENCES agent_tasks (deployment_namespace, task_id)
                    ON DELETE CASCADE,
                FOREIGN KEY (deployment_namespace, event_id)
                    REFERENCES session_events (deployment_namespace, event_id),
                FOREIGN KEY (deployment_namespace, task_id, segment_id)
                    REFERENCES execution_segments (
                        deployment_namespace, task_id, session_id
                    )
            )
            """,
        ),
    ),
    Migration(
        version=6,
        name="model_and_tool_event_projections",
        statements=(
            """
            ALTER TABLE session_events
            ADD CONSTRAINT session_events_projection_source
            UNIQUE (deployment_namespace, session_id, sequence, event_id)
            """,
            """
            CREATE TABLE model_call_projections (
                deployment_namespace TEXT NOT NULL,
                session_id UUID NOT NULL,
                sequence BIGINT NOT NULL CHECK (sequence >= 0),
                event_id UUID NOT NULL,
                provider TEXT,
                model_name TEXT,
                input_tokens BIGINT, estimated_input_tokens BIGINT,
                input_token_limit BIGINT, input_token_estimate_error BIGINT,
                output_tokens BIGINT, total_tokens BIGINT, latency_ms BIGINT,
                cache_hit BOOLEAN, cost_usd DOUBLE PRECISION,
                assistant_message TEXT NOT NULL, tool_call_count INTEGER NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (deployment_namespace, session_id, sequence),
                UNIQUE (deployment_namespace, event_id),
                FOREIGN KEY (deployment_namespace, session_id, sequence, event_id)
                    REFERENCES session_events (
                        deployment_namespace, session_id, sequence, event_id
                    )
            )
            """,
            """
            CREATE TABLE tool_run_projections (
                deployment_namespace TEXT NOT NULL,
                session_id UUID NOT NULL,
                sequence BIGINT NOT NULL CHECK (sequence >= 0),
                event_id UUID NOT NULL,
                tool_name TEXT NOT NULL, status TEXT NOT NULL,
                idempotency_key TEXT, output TEXT NOT NULL, artifact_uri TEXT,
                created_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (deployment_namespace, session_id, sequence),
                UNIQUE (deployment_namespace, event_id),
                FOREIGN KEY (deployment_namespace, session_id, sequence, event_id)
                    REFERENCES session_events (
                        deployment_namespace, session_id, sequence, event_id
                    )
            )
            """,
        ),
    ),
    Migration(
        version=7,
        name="fenced_context_lifecycle",
        statements=(
            """
            ALTER TABLE session_events
            ADD CONSTRAINT session_events_session_event_identity
            UNIQUE (deployment_namespace, session_id, event_id)
            """,
            """
            CREATE TABLE context_capsule_artifacts (
                deployment_namespace TEXT NOT NULL,
                capsule_id TEXT NOT NULL CHECK (length(btrim(capsule_id)) > 0),
                artifact_id UUID NOT NULL,
                session_id UUID NOT NULL,
                payload JSONB NOT NULL,
                payload_sha256 TEXT NOT NULL CHECK (length(payload_sha256) = 64),
                source_hash TEXT NOT NULL CHECK (length(source_hash) = 64),
                compaction_event_id UUID NOT NULL,
                capsule_event_id UUID NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (deployment_namespace, capsule_id),
                UNIQUE (deployment_namespace, artifact_id),
                UNIQUE (deployment_namespace, compaction_event_id),
                UNIQUE (deployment_namespace, capsule_event_id),
                UNIQUE (
                    deployment_namespace, session_id, compaction_event_id
                ),
                UNIQUE (
                    deployment_namespace, session_id, capsule_event_id
                ),
                UNIQUE (
                    deployment_namespace, session_id, capsule_id, artifact_id
                ),
                FOREIGN KEY (deployment_namespace, session_id)
                    REFERENCES session_streams (deployment_namespace, session_id),
                FOREIGN KEY (
                    deployment_namespace, session_id, compaction_event_id
                ) REFERENCES session_events (
                    deployment_namespace, session_id, event_id
                ),
                FOREIGN KEY (
                    deployment_namespace, session_id, capsule_event_id
                ) REFERENCES session_events (
                    deployment_namespace, session_id, event_id
                )
            )
            """,
            """
            CREATE TABLE active_context_projections (
                deployment_namespace TEXT NOT NULL,
                session_id UUID NOT NULL,
                capsule_id TEXT NOT NULL,
                artifact_id UUID NOT NULL,
                source_hash TEXT NOT NULL CHECK (length(source_hash) = 64),
                event_sequence BIGINT NOT NULL CHECK (event_sequence >= 0),
                updated_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (deployment_namespace, session_id),
                FOREIGN KEY (
                    deployment_namespace, session_id, capsule_id, artifact_id
                ) REFERENCES context_capsule_artifacts (
                    deployment_namespace, session_id, capsule_id, artifact_id
                )
            )
            """,
        ),
    ),
    HANDOFF_MIGRATION,
    ARTIFACT_PAYLOAD_MIGRATION,
    GOVERNED_MEMORY_MIGRATION,
    MEMORY_DELIVERY_MIGRATION,
    NATIVE_MEMORY_MIGRATION,
    PROVIDER_CONTINUATION_MIGRATION,
    CONTROL_PLANE_MIGRATION,
    DELIVERY_TRANSACTION_MIGRATION,
    MIGRATION_RECOVERY_MIGRATION,
    HOST_AUTH_MIGRATION,
    WORKSPACE_CONTROL_MIGRATION,
    AGENT_REGISTRY_MIGRATION,
    WORKSPACE_DEFINITION_SNAPSHOT_MIGRATION,
    GOVERNED_MEMORY_SCOPE_MIGRATION,
    AGENT_RELEASE_ENFORCEMENT_MIGRATION,
    SESSION_TENANT_NAMESPACE_MIGRATION,
    HOST_CONNECTOR_MIGRATION,
)
