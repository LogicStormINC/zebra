"""Explicit, checksum-verified PostgreSQL migrations for the control plane."""

import hashlib
from dataclasses import dataclass

import psycopg


class PostgresMigrationError(RuntimeError):
    """Raised when the database migration history is not trusted."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        content = "\n-- statement --\n".join(self.statements).encode()
        return hashlib.sha256(content).hexdigest()


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
)

_MIGRATION_LOCK_ID = 9_187_330_641


def apply_postgres_migrations(dsn: str) -> None:
    """Apply known migrations under one transaction-scoped advisory lock."""
    with psycopg.connect(dsn) as connection:
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK_ID,))
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS zebra_schema_migrations (
                version BIGINT PRIMARY KEY,
                name TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        applied = {
            row[0]: (row[1], row[2])
            for row in connection.execute(
                "SELECT version, name, checksum FROM zebra_schema_migrations"
            ).fetchall()
        }
        known_versions = {migration.version for migration in MIGRATIONS}
        unknown_versions = sorted(set(applied) - known_versions)
        if unknown_versions:
            raise PostgresMigrationError(
                f"database has unknown migration versions: {unknown_versions}"
            )
        for migration in MIGRATIONS:
            existing = applied.get(migration.version)
            if existing is not None:
                if existing != (migration.name, migration.checksum):
                    raise PostgresMigrationError(
                        f"migration {migration.version} checksum or name does not match"
                    )
                continue
            for statement in migration.statements:
                connection.execute(statement)
            connection.execute(
                """
                INSERT INTO zebra_schema_migrations (version, name, checksum)
                VALUES (%s, %s, %s)
                """,
                (migration.version, migration.name, migration.checksum),
            )
