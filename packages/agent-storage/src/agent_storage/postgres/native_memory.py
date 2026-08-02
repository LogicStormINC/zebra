"""PostgreSQL-native, provider-free Memory Gateway implementation."""

from __future__ import annotations

from typing import Any, cast

from agent_core.domain.identifiers import MemoryId
from agent_core.ports.agent_memory_gateway import (
    AgentMemoryGatewayPort,
    ConfirmedMemoryPublication,
    MemoryGatewayDeleteRequest,
    MemoryGatewayHit,
    MemoryGatewayMutationResult,
    MemoryGatewaySearchRequest,
    MemoryGatewaySearchResult,
    MemoryGatewayStatus,
)
from psycopg import errors

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.native_memory_types import (
    NativeMemoryConflictError,
    NativeMemoryError,
    NativeMemoryMutation,
    NativeMemoryNamespaceError,
    NativeMemoryOperation,
    NativeMemoryRecallHit,
    NativeMemoryReset,
    NativeMemoryStaleGenerationError,
    NativeOperation,
    NativeResultStatus,
)


class PostgresNativeMemoryGateway(AgentMemoryGatewayPort):
    """Store authoritative Memory content and its retrieval projection atomically.

    The class is intentionally storage-only. It is compatible with the existing
    provider-neutral Gateway Port, while the ``*_native`` methods expose the
    generation/CAS and reset operations needed by a later composition task.
    """

    def __init__(self, dsn: str, *, deployment_namespace: str, scope_id: str = "default") -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self._scope_id = _required_text(scope_id, field_name="scope_id", maximum=255)

    @property
    def deployment_namespace(self) -> str:
        return self._database.deployment_namespace

    @property
    def scope_id(self) -> str:
        return self._scope_id

    def publish(
        self,
        publication: ConfirmedMemoryPublication,
    ) -> MemoryGatewayMutationResult:
        try:
            mutation = self.publish_native(publication)
        except (
            NativeMemoryConflictError,
            NativeMemoryNamespaceError,
            NativeMemoryStaleGenerationError,
        ) as error:
            return _degraded(str(error))
        return MemoryGatewayMutationResult(
            status=MemoryGatewayStatus.SUCCEEDED,
            provider_ref=str(mutation.memory_id),
            detail="replayed" if mutation.replayed else None,
        )

    def search(self, request: MemoryGatewaySearchRequest) -> MemoryGatewaySearchResult:
        if request.namespace != self.deployment_namespace:
            return _search_degraded("namespace_mismatch")
        hits = self.recall(
            request.query,
            limit=request.limit,
        )
        return MemoryGatewaySearchResult(
            status=MemoryGatewayStatus.SUCCEEDED,
            hits=tuple(
                MemoryGatewayHit(
                    memory_id=hit.memory_id,
                    provider_ref=str(hit.memory_id),
                    provider_score=hit.score,
                )
                for hit in hits
            ),
        )

    def delete(self, request: MemoryGatewayDeleteRequest) -> MemoryGatewayMutationResult:
        try:
            mutation = self.delete_native(request)
        except (
            NativeMemoryConflictError,
            NativeMemoryNamespaceError,
            NativeMemoryStaleGenerationError,
        ) as error:
            return _degraded(str(error))
        if mutation.result_status == "not_found":
            return MemoryGatewayMutationResult(
                status=MemoryGatewayStatus.NOT_FOUND,
                detail="replayed" if mutation.replayed else "memory_not_found",
            )
        return MemoryGatewayMutationResult(
            status=MemoryGatewayStatus.SUCCEEDED,
            provider_ref=str(mutation.memory_id),
            detail="replayed" if mutation.replayed else None,
        )

    def publish_native(
        self,
        publication: ConfirmedMemoryPublication,
        *,
        expected_generation: int | None = None,
        memory_type: str = "preference",
        topic: str = "general",
    ) -> NativeMemoryMutation:
        self._assert_namespace(publication.namespace)
        memory_type = _required_text(memory_type, field_name="memory_type", maximum=255)
        topic = _required_text(topic, field_name="topic", maximum=255)
        with self._database.connect() as connection:
            with connection.transaction():
                existing = self._read_operation(connection, publication.idempotency_key)
                if existing is not None:
                    return self._replay(existing, operation="publish")
                scope = self._lock_scope(connection)
                existing = self._read_operation(connection, publication.idempotency_key)
                if existing is not None:
                    return self._replay(existing, operation="publish")
                generation = _check_generation(scope["current_generation"], expected_generation)
                self._insert_operation(
                    connection,
                    operation_id=publication.idempotency_key,
                    scope_id=self._scope_id,
                    generation=generation,
                    memory_id=publication.memory_id,
                    operation="publish",
                    result_status="committed",
                )
                try:
                    connection.execute(
                        """
                        INSERT INTO native_memory_authority (
                            deployment_namespace, scope_id, generation, memory_id,
                            operation_id, content, memory_type, topic, status
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'confirmed')
                        """,
                        (
                            self.deployment_namespace,
                            self._scope_id,
                            generation,
                            publication.memory_id,
                            publication.idempotency_key,
                            publication.text,
                            memory_type,
                            topic,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO native_memory_retrieval (
                            deployment_namespace, memory_id, scope_id, generation, document
                        ) VALUES (%s, %s, %s, %s, to_tsvector('simple', %s))
                        """,
                        (
                            self.deployment_namespace,
                            publication.memory_id,
                            self._scope_id,
                            generation,
                            f"{publication.text} {topic}",
                        ),
                    )
                except Exception as error:
                    if _is_unique_violation(error):
                        raise NativeMemoryConflictError(
                            "memory identity is already committed"
                        ) from error
                    raise
                return NativeMemoryMutation(
                    memory_id=publication.memory_id,
                    operation_id=publication.idempotency_key,
                    scope_id=self._scope_id,
                    generation=generation,
                    result_status="committed",
                    replayed=False,
                )

    def delete_native(
        self,
        request: MemoryGatewayDeleteRequest,
        *,
        expected_generation: int | None = None,
    ) -> NativeMemoryMutation:
        self._assert_namespace(request.namespace)
        with self._database.connect() as connection:
            with connection.transaction():
                existing = self._read_operation(connection, request.idempotency_key)
                if existing is not None:
                    return self._replay(existing, operation="delete")
                scope = self._lock_scope(connection)
                existing = self._read_operation(connection, request.idempotency_key)
                if existing is not None:
                    return self._replay(existing, operation="delete")
                generation = _check_generation(scope["current_generation"], expected_generation)
                authority = connection.execute(
                    """
                    SELECT memory_id FROM native_memory_authority
                    WHERE deployment_namespace = %s AND scope_id = %s
                      AND generation = %s AND memory_id = %s
                    FOR UPDATE
                    """,
                    (self.deployment_namespace, self._scope_id, generation, request.memory_id),
                ).fetchone()
                result_status: NativeResultStatus = (
                    "committed" if authority is not None else "not_found"
                )
                self._insert_operation(
                    connection,
                    operation_id=request.idempotency_key,
                    scope_id=self._scope_id,
                    generation=generation,
                    memory_id=request.memory_id,
                    operation="delete",
                    result_status=result_status,
                )
                if authority is not None:
                    connection.execute(
                        """
                        DELETE FROM native_memory_retrieval
                        WHERE deployment_namespace = %s AND memory_id = %s
                        """,
                        (self.deployment_namespace, request.memory_id),
                    )
                    connection.execute(
                        """
                        DELETE FROM native_memory_authority
                        WHERE deployment_namespace = %s AND memory_id = %s
                        """,
                        (self.deployment_namespace, request.memory_id),
                    )
                return NativeMemoryMutation(
                    memory_id=request.memory_id,
                    operation_id=request.idempotency_key,
                    scope_id=self._scope_id,
                    generation=generation,
                    result_status=result_status,
                    replayed=False,
                )

    def reset_scope(self, *, expected_generation: int | None = None) -> NativeMemoryReset:
        with self._database.connect() as connection:
            with connection.transaction():
                scope = self._lock_scope(connection)
                previous_generation = int(scope["current_generation"])
                _check_generation(previous_generation, expected_generation)
                generation = previous_generation + 1
                connection.execute(
                    """
                    DELETE FROM native_memory_retrieval
                    WHERE deployment_namespace = %s AND scope_id = %s AND generation < %s
                    """,
                    (self.deployment_namespace, self._scope_id, generation),
                )
                deleted = connection.execute(
                    """
                    DELETE FROM native_memory_authority
                    WHERE deployment_namespace = %s AND scope_id = %s AND generation < %s
                    """,
                    (self.deployment_namespace, self._scope_id, generation),
                ).rowcount
                connection.execute(
                    """
                    UPDATE native_memory_scopes
                    SET current_generation = %s, updated_at = transaction_timestamp()
                    WHERE deployment_namespace = %s AND scope_id = %s
                    """,
                    (generation, self.deployment_namespace, self._scope_id),
                )
                return NativeMemoryReset(
                    scope_id=self._scope_id,
                    previous_generation=previous_generation,
                    generation=generation,
                    deleted_memories=deleted,
                )

    def current_generation(self) -> int:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT current_generation FROM native_memory_scopes
                WHERE deployment_namespace = %s AND scope_id = %s
                """,
                (self.deployment_namespace, self._scope_id),
            ).fetchone()
        return 1 if row is None else int(row["current_generation"])

    def get_operation(self, operation_id: str) -> NativeMemoryOperation | None:
        operation_id = _required_text(operation_id, field_name="operation_id", maximum=256)
        with self._database.connect() as connection:
            row = self._read_operation(connection, operation_id)
        return None if row is None else _operation_from_row(row)

    def recall(
        self,
        query: str,
        *,
        limit: int = 10,
        topic: str | None = None,
    ) -> tuple[NativeMemoryRecallHit, ...]:
        query = _required_text(query, field_name="query", maximum=4_096)
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        topic = None if topic is None else _required_text(topic, field_name="topic", maximum=255)
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT current_generation FROM native_memory_scopes
                WHERE deployment_namespace = %s AND scope_id = %s
                """,
                (self.deployment_namespace, self._scope_id),
            ).fetchone()
            if row is None:
                return ()
            rows = connection.execute(
                """
                SELECT a.memory_id, a.content, a.memory_type, a.topic,
                       ts_rank_cd(r.document, plainto_tsquery('simple', %s)) AS score
                FROM native_memory_authority a
                JOIN native_memory_retrieval r USING (deployment_namespace, memory_id)
                WHERE a.deployment_namespace = %s AND a.scope_id = %s
                  AND a.generation = %s AND a.status = 'confirmed'
                  AND a.deleted_at IS NULL
                  AND r.document @@ plainto_tsquery('simple', %s)
                  AND (%s::text IS NULL OR a.topic = %s::text)
                ORDER BY score DESC, a.memory_id
                LIMIT %s
                """,
                (
                    query,
                    self.deployment_namespace,
                    self._scope_id,
                    row["current_generation"],
                    query,
                    topic,
                    topic,
                    limit,
                ),
            ).fetchall()
        return tuple(
            NativeMemoryRecallHit(
                memory_id=MemoryId(item["memory_id"]),
                score=float(item["score"]),
                content=item["content"],
                memory_type=item["memory_type"],
                topic=item["topic"],
            )
            for item in rows
        )

    def _lock_scope(self, connection: Any) -> dict[str, Any]:
        connection.execute(
            """
            INSERT INTO native_memory_scopes (deployment_namespace, scope_id, current_generation)
            VALUES (%s, %s, 1)
            ON CONFLICT (deployment_namespace, scope_id) DO NOTHING
            """,
            (self.deployment_namespace, self._scope_id),
        )
        row = connection.execute(
            """
            SELECT current_generation FROM native_memory_scopes
            WHERE deployment_namespace = %s AND scope_id = %s
            FOR UPDATE
            """,
            (self.deployment_namespace, self._scope_id),
        ).fetchone()
        if row is None:  # pragma: no cover - protected by the INSERT above
            raise NativeMemoryError("native memory scope disappeared")
        return cast(dict[str, Any], row)

    def _read_operation(self, connection: Any, operation_id: str) -> dict[str, Any] | None:
        row = connection.execute(
            """
            SELECT operation_id, memory_id, scope_id, generation, operation, result_status
            FROM native_memory_operations
            WHERE deployment_namespace = %s AND operation_id = %s
            """,
            (self.deployment_namespace, operation_id),
        ).fetchone()
        return cast(dict[str, Any] | None, row)

    def _insert_operation(
        self,
        connection: Any,
        *,
        operation_id: str,
        scope_id: str,
        generation: int,
        memory_id: MemoryId,
        operation: NativeOperation,
        result_status: NativeResultStatus,
    ) -> None:
        try:
            connection.execute(
                """
                INSERT INTO native_memory_operations (
                    deployment_namespace, operation_id, scope_id, generation,
                    memory_id, operation, result_status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    self.deployment_namespace,
                    operation_id,
                    scope_id,
                    generation,
                    memory_id,
                    operation,
                    result_status,
                ),
            )
        except errors.UniqueViolation as error:
            raise NativeMemoryConflictError("operation identity is already committed") from error

    def _replay(self, row: dict[str, Any], *, operation: NativeOperation) -> NativeMemoryMutation:
        if row["scope_id"] != self._scope_id or row["operation"] != operation:
            raise NativeMemoryConflictError("idempotency key belongs to another operation")
        return NativeMemoryMutation(
            memory_id=MemoryId(row["memory_id"]),
            operation_id=row["operation_id"],
            scope_id=row["scope_id"],
            generation=int(row["generation"]),
            result_status=row["result_status"],
            replayed=True,
        )

    def _assert_namespace(self, namespace: str) -> None:
        if namespace != self.deployment_namespace:
            raise NativeMemoryNamespaceError("memory namespace does not match PostgreSQL store")


def _operation_from_row(row: dict[str, Any]) -> NativeMemoryOperation:
    return NativeMemoryOperation(
        operation_id=row["operation_id"],
        memory_id=MemoryId(row["memory_id"]),
        scope_id=row["scope_id"],
        generation=int(row["generation"]),
        operation=row["operation"],
        result_status=row["result_status"],
    )


def _check_generation(current: object, expected: int | None) -> int:
    current_generation = int(cast(int | str, current))
    if expected is not None and expected != current_generation:
        raise NativeMemoryStaleGenerationError(
            f"expected generation {expected}, current generation is {current_generation}"
        )
    return current_generation


def _required_text(value: str, *, field_name: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field_name} must be non-blank and at most {maximum} characters")
    return normalized


def _is_unique_violation(error: Exception) -> bool:
    return isinstance(error, errors.UniqueViolation)


def _degraded(detail: str) -> MemoryGatewayMutationResult:
    return MemoryGatewayMutationResult(status=MemoryGatewayStatus.DEGRADED, detail=detail)


def _search_degraded(detail: str) -> MemoryGatewaySearchResult:
    return MemoryGatewaySearchResult(status=MemoryGatewayStatus.DEGRADED, detail=detail)
