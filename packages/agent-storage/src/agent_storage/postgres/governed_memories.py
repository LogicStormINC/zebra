"""Namespace-bound PostgreSQL governed Memory authority Store."""

import base64
import binascii
import hashlib
import hmac
import json
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from agent_core.domain.governed_memories import (
    GovernedMemoryConflictError,
    GovernedMemoryEntry,
    GovernedMemoryManagementContext,
    GovernedMemoryTombstone,
)
from agent_core.domain.governed_memory_operations import (
    AdministrativeMemoryReviewRequest,
    WorkerMemoryMutationPlan,
)
from agent_core.domain.governed_memory_receipts import GovernedMemoryCommitResult
from agent_core.domain.identifiers import MemoryId
from agent_core.domain.memories import MemoryQuery, MemoryRecord, MemoryVisibility
from agent_core.domain.memory_delivery import MemoryDeliveryScope
from agent_core.ports.aggregate_mutation import AdministrativeMutationCAS, WorkerMutationAuthority
from agent_core.ports.governed_memory_store import (
    GovernedMemoryScanCursor,
    GovernedMemoryScanPage,
    GovernedMemoryScanQuery,
    GovernedMemoryStorePort,
)

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.governed_memory_rows import authority_from_row, query_records
from agent_storage.postgres.governed_memory_transaction_support import _lock_session
from agent_storage.postgres.governed_memory_transactions import (
    commit_administrative,
    commit_worker,
)
from agent_storage.postgres.leases import assert_current_lease_fence

_SNAPSHOT_TTL = timedelta(minutes=30)
_MAX_SNAPSHOTS = 32


class PostgresGovernedMemoryStore(GovernedMemoryStorePort):
    """Authoritative rows and restart-safe, content-free management snapshots."""

    def __init__(
        self,
        dsn: str,
        *,
        deployment_namespace: str,
        cursor_signing_key: bytes,
        delivery_scope: MemoryDeliveryScope | None = None,
    ) -> None:
        if len(cursor_signing_key) < 32:
            raise ValueError("Memory scan cursor signing key must contain at least 32 bytes")
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        if (
            delivery_scope is not None
            and delivery_scope.deployment_namespace != deployment_namespace
        ):
            raise ValueError("Memory delivery scope namespace must match governed Memory store")
        self._delivery_scope = delivery_scope
        self._cursor_key = hmac.new(
            cursor_signing_key,
            f"governed-memory-scan\0{deployment_namespace}".encode(),
            hashlib.sha256,
        ).digest()

    def get(self, memory_id: MemoryId) -> MemoryRecord | None:
        with self._database.connect() as connection:
            row = self._read_row(connection, memory_id)
        authority = None if row is None else authority_from_row(row)
        return authority.record if isinstance(authority, GovernedMemoryEntry) else None

    def list(self, query: MemoryQuery) -> list[MemoryRecord]:
        with self._database.connect() as connection:
            return query_records(connection, self._database.deployment_namespace, query)

    def list_for_worker(
        self, query: MemoryQuery, *, authority: WorkerMutationAuthority
    ) -> tuple[GovernedMemoryEntry, ...]:
        namespace = self._database.deployment_namespace
        if authority.deployment_namespace != namespace:
            raise GovernedMemoryConflictError("Worker Memory namespace does not match authority")
        with self._database.connect() as connection:
            assert_current_lease_fence(
                connection, namespace, authority.session_id, authority.lease_fence
            )
            _lock_session(
                connection,
                namespace,
                authority.session_id,
                authority.expected_stream_revision,
            )
            records = query_records(connection, namespace, query)
            rows = [self._read_row(connection, item.memory_id) for item in records]
        return tuple(
            item
            for row in rows
            if row is not None
            and isinstance((item := authority_from_row(row)), GovernedMemoryEntry)
        )

    def get_authority(
        self,
        memory_id: MemoryId,
        *,
        management: GovernedMemoryManagementContext,
    ) -> GovernedMemoryEntry | GovernedMemoryTombstone | None:
        del management
        with self._database.connect() as connection:
            row = self._read_row(connection, memory_id)
        return None if row is None else authority_from_row(row)

    def commit_worker_candidates(
        self, plan: WorkerMemoryMutationPlan, *, authority: WorkerMutationAuthority
    ) -> GovernedMemoryCommitResult:
        with self._database.connect() as connection:
            return commit_worker(
                connection,
                self._database.deployment_namespace,
                plan,
                authority,
                delivery_scope=self._delivery_scope,
            )

    def commit_administrative_review(
        self,
        request: AdministrativeMemoryReviewRequest,
        *,
        authority: AdministrativeMutationCAS,
    ) -> GovernedMemoryCommitResult:
        with self._database.connect() as connection:
            return commit_administrative(
                connection,
                self._database.deployment_namespace,
                request,
                authority,
                delivery_scope=self._delivery_scope,
            )

    def scan_confirmed(
        self,
        query: GovernedMemoryScanQuery,
        *,
        management: GovernedMemoryManagementContext,
    ) -> GovernedMemoryScanPage:
        with self._database.connect() as connection:
            snapshot_id, offset, digest = self._resolve_scan(connection, query, management)
            rows = connection.execute(
                """
                SELECT i.ordinal, r.*,
                       (r.status = 'confirmed' AND (
                           r.expires_at IS NULL OR r.expires_at > transaction_timestamp()
                       )) AS currently_eligible
                FROM governed_memory_scan_items i
                JOIN governed_memory_records r USING (deployment_namespace, memory_id)
                WHERE i.deployment_namespace = %s AND i.snapshot_id = %s
                  AND i.ordinal >= %s
                ORDER BY i.ordinal LIMIT %s
                """,
                (
                    self._database.deployment_namespace,
                    snapshot_id,
                    offset,
                    query.limit + 1,
                ),
            ).fetchall()
            page_rows = rows[: query.limit]
            # captured_revision is audit evidence only: semantic content/scope are immutable,
            # so a still-confirmed row may be returned at its latest lifecycle revision.
            next_offset = offset if not page_rows else page_rows[-1]["ordinal"] + 1
            entries = [
                item
                for row in page_rows
                if row["currently_eligible"]
                and isinstance((item := authority_from_row(row)), GovernedMemoryEntry)
            ]
            remaining = connection.execute(
                """
                SELECT 1 FROM governed_memory_scan_items
                WHERE deployment_namespace = %s AND snapshot_id = %s AND ordinal >= %s
                LIMIT 1
                """,
                (self._database.deployment_namespace, snapshot_id, next_offset),
            ).fetchone()
            cursor = None
            if remaining is not None:
                cursor = GovernedMemoryScanCursor(
                    snapshot_token=str(snapshot_id),
                    position_token=self._sign(snapshot_id, next_offset, digest),
                )
            return GovernedMemoryScanPage(entries=tuple(entries), next_cursor=cursor)

    def _resolve_scan(
        self,
        connection: Any,
        query: GovernedMemoryScanQuery,
        management: GovernedMemoryManagementContext,
    ) -> tuple[UUID, int, str]:
        digest = _scope_digest(query)
        if query.cursor is None:
            return self._materialize_scan(connection, query, digest, management), 0, digest
        try:
            snapshot_id = UUID(query.cursor.snapshot_token)
            offset = self._verify(query.cursor.position_token, snapshot_id, digest)
        except (ValueError, KeyError, json.JSONDecodeError, binascii.Error) as error:
            raise GovernedMemoryConflictError("Memory scan cursor is invalid") from error
        row = connection.execute(
            """
            SELECT scope_digest, operation_id, operator, reason
            FROM governed_memory_scan_snapshots
            WHERE deployment_namespace = %s AND snapshot_id = %s
              AND expires_at > transaction_timestamp()
            """,
            (self._database.deployment_namespace, snapshot_id),
        ).fetchone()
        if (
            row is None
            or row["scope_digest"] != digest
            or row["operation_id"] != management.operation_id
            or row["operator"] != management.operator
            or row["reason"] != management.reason
        ):
            raise GovernedMemoryConflictError("Memory scan snapshot expired or scope changed")
        return snapshot_id, offset, digest

    def _materialize_scan(
        self,
        connection: Any,
        query: GovernedMemoryScanQuery,
        digest: str,
        management: GovernedMemoryManagementContext,
    ) -> UUID:
        namespace = self._database.deployment_namespace
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"memory-snapshots:{namespace}",),
        )
        connection.execute(
            """DELETE FROM governed_memory_scan_snapshots
            WHERE deployment_namespace = %s AND expires_at <= transaction_timestamp()""",
            (namespace,),
        )
        existing = connection.execute(
            """SELECT snapshot_id, scope_digest, operator, reason
            FROM governed_memory_scan_snapshots
            WHERE deployment_namespace = %s AND operation_id = %s""",
            (namespace, management.operation_id),
        ).fetchone()
        if existing is not None:
            if (
                existing["scope_digest"] != digest
                or existing["operator"] != management.operator
                or existing["reason"] != management.reason
            ):
                raise GovernedMemoryConflictError("Memory scan operation identity was reused")
            snapshot_id = existing["snapshot_id"]
            if not isinstance(snapshot_id, UUID):
                raise GovernedMemoryConflictError("Memory scan snapshot identity is invalid")
            return snapshot_id
        count = connection.execute(
            """SELECT count(*) AS count FROM governed_memory_scan_snapshots
            WHERE deployment_namespace = %s""",
            (namespace,),
        ).fetchone()["count"]
        if count >= _MAX_SNAPSHOTS:
            raise GovernedMemoryConflictError("too many active Memory scan snapshots")
        snapshot_id = uuid4()
        scope = _scope_payload(query)
        connection.execute(
            """
            INSERT INTO governed_memory_scan_snapshots
            (deployment_namespace, snapshot_id, operation_id, operator, reason,
             scope_digest, query_json, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, transaction_timestamp() + %s)
            """,
            (
                namespace,
                snapshot_id,
                management.operation_id,
                management.operator,
                management.reason,
                digest,
                json.dumps(scope),
                _SNAPSHOT_TTL,
            ),
        )
        connection.execute(
            f"""
            INSERT INTO governed_memory_scan_items
            (deployment_namespace, snapshot_id, ordinal, memory_id, captured_revision)
            SELECT deployment_namespace, %s, row_number() OVER (ORDER BY memory_id) - 1,
                   memory_id, revision
            FROM governed_memory_records
            WHERE deployment_namespace = %s AND status = 'confirmed'
              AND visibility = %s AND {_scope_column(scope["visibility"])} = %s
              AND (expires_at IS NULL OR expires_at > transaction_timestamp())
              AND (%s::text[] IS NULL OR memory_type = ANY(%s::text[]))
            ORDER BY memory_id
            """,
            (
                snapshot_id,
                namespace,
                scope["visibility"],
                scope["scope_value"],
                scope["memory_types"] or None,
                scope["memory_types"] or None,
            ),
        )
        return snapshot_id

    def _sign(self, snapshot_id: UUID, offset: int, digest: str) -> str:
        raw = json.dumps([str(snapshot_id), offset, digest], separators=(",", ":")).encode()
        signature = hmac.new(self._cursor_key, raw, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(raw + signature).decode().rstrip("=")

    def _verify(self, token: str, snapshot_id: UUID, digest: str) -> int:
        encoded = token + "=" * (-len(token) % 4)
        value = base64.urlsafe_b64decode(encoded.encode())
        raw, signature = value[:-32], value[-32:]
        if not hmac.compare_digest(
            signature, hmac.new(self._cursor_key, raw, hashlib.sha256).digest()
        ):
            raise ValueError("invalid signature")
        stored_id, offset, stored_digest = json.loads(raw)
        if (
            stored_id != str(snapshot_id)
            or stored_digest != digest
            or not isinstance(offset, int)
            or isinstance(offset, bool)
            or offset < 0
        ):
            raise ValueError("cursor scope mismatch")
        return offset

    def _read_row(self, connection: Any, memory_id: MemoryId) -> dict[str, Any] | None:
        return cast(
            dict[str, Any] | None,
            connection.execute(
                """SELECT * FROM governed_memory_records
            WHERE deployment_namespace = %s AND memory_id = %s""",
                (self._database.deployment_namespace, memory_id),
            ).fetchone(),
        )


def _scope_payload(query: GovernedMemoryScanQuery) -> dict[str, Any]:
    scope = query.scope
    assert scope.visibility is not None
    value = {
        MemoryVisibility.REPO: scope.repo_id,
        MemoryVisibility.USER: scope.user_id,
        MemoryVisibility.TENANT: scope.tenant_id,
    }[scope.visibility]
    return {
        "visibility": scope.visibility.value,
        "scope_value": value,
        "memory_types": sorted(item.value for item in scope.memory_types),
    }


def _scope_digest(query: GovernedMemoryScanQuery) -> str:
    return hashlib.sha256(
        json.dumps(_scope_payload(query), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _scope_column(visibility: object) -> str:
    return {"repo": "repo_id", "user": "user_id", "tenant": "tenant_id"}[str(visibility)]
