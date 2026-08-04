"""Fenced, Event-derived PostgreSQL Model and Tool projections."""

from typing import Any

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.model_calls import ModelCallRecord
from agent_core.domain.tool_runs import ToolRunRecord
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.model_tool_projection import ModelToolProjectionPort

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.events import read_event_in_transaction
from agent_storage.postgres.leases import assert_current_lease_fence


class PostgresModelToolProjectionConflictError(ValueError):
    """A projection key was reused for different canonical Event content."""


class PostgresModelToolProjectionStore(ModelToolProjectionPort):
    """Indexes committed canonical Events; it never stores Artifact payload bytes."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    def index_worker_event(
        self, event: SessionEvent, *, authority: WorkerMutationAuthority
    ) -> ModelCallRecord | ToolRunRecord | None:
        self._validate_authority(event, authority)
        with self._database.connect() as connection:
            assert_current_lease_fence(
                connection,
                self._database.deployment_namespace,
                event.session_id,
                authority.lease_fence,
            )
            _assert_worker_stream_revision(
                connection,
                self._database.deployment_namespace,
                event,
                authority,
            )
            return index_event_in_transaction(
                connection, self._database.deployment_namespace, event
            )

    def replay_session(self, session_id: SessionId) -> int:
        """Management-only repair from committed Events; no lease or payload I/O."""
        with self._database.connect() as connection:
            rows = connection.execute(
                """SELECT event_id, session_id, sequence, event_type, payload, actor,
                          created_at, causation_id, correlation_id, idempotency_key,
                          policy_version, model_profile FROM session_events
                   WHERE deployment_namespace = %s AND session_id = %s ORDER BY sequence""",
                (self._database.deployment_namespace, session_id),
            ).fetchall()
            return sum(
                index_event_in_transaction(
                    connection,
                    self._database.deployment_namespace,
                    SessionEvent.model_validate(row),
                )
                is not None
                for row in rows
            )

    def list_model_calls(self, session_id: SessionId) -> list[ModelCallRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT session_id, sequence, provider, model_name, input_tokens,
                       estimated_input_tokens, input_token_limit,
                       input_token_estimate_error, output_tokens, total_tokens,
                       latency_ms, cache_hit, cost_usd, assistant_message,
                       tool_call_count, created_at
                FROM model_call_projections
                WHERE deployment_namespace = %s AND session_id = %s
                ORDER BY sequence ASC
                """,
                (self._database.deployment_namespace, session_id),
            ).fetchall()
        return [ModelCallRecord.model_validate(row) for row in rows]

    def list_tool_runs(self, session_id: SessionId) -> list[ToolRunRecord]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT session_id, sequence, tool_name, status, idempotency_key,
                       output, artifact_uri, created_at
                FROM tool_run_projections
                WHERE deployment_namespace = %s AND session_id = %s
                ORDER BY sequence ASC
                """,
                (self._database.deployment_namespace, session_id),
            ).fetchall()
        return [ToolRunRecord.model_validate(row) for row in rows]

    def _validate_authority(self, event: SessionEvent, authority: WorkerMutationAuthority) -> None:
        if authority.deployment_namespace != self._database.deployment_namespace:
            raise LeaseLostError("model/tool mutation authority belongs to another namespace")
        if authority.session_id != event.session_id:
            raise LeaseLostError("model/tool mutation authority belongs to another session")


def _assert_worker_stream_revision(
    connection: Any,
    deployment_namespace: str,
    event: SessionEvent,
    authority: WorkerMutationAuthority,
) -> None:
    """Bind a projection write to the stream revision preceding its Event."""
    if event.sequence != authority.expected_stream_revision + 1:
        raise PostgresModelToolProjectionConflictError(
            "projection Event does not follow the expected stream revision"
        )
    row = connection.execute(
        """
        SELECT current_version FROM session_streams
        WHERE deployment_namespace = %s AND session_id = %s
        FOR SHARE
        """,
        (deployment_namespace, event.session_id),
    ).fetchone()
    if row is None or row["current_version"] < event.sequence:
        raise PostgresModelToolProjectionConflictError(
            "projection Event stream revision drifted before indexing"
        )


def index_event_in_transaction(
    connection: Any, deployment_namespace: str, event: SessionEvent
) -> ModelCallRecord | ToolRunRecord | None:
    canonical = read_event_in_transaction(connection, deployment_namespace, event.event_id)
    if canonical != event:
        raise PostgresModelToolProjectionConflictError(
            "projection input does not match its canonical Event"
        )
    if event.event_type is EventType.MODEL_RESPONSE_RECEIVED:
        record = _model_record(event)
        _upsert(
            connection, "model_call_projections", _model_values(deployment_namespace, event, record)
        )
        return record
    if event.event_type in {EventType.TOOL_EXECUTION_COMPLETED, EventType.TOOL_EXECUTION_FAILED}:
        tool_record = _tool_record(event)
        _upsert(
            connection,
            "tool_run_projections",
            _tool_values(deployment_namespace, event, tool_record),
        )
        return tool_record
    return None


def _upsert(connection: Any, table: str, values: tuple[object, ...]) -> None:
    columns = _MODEL_COLUMNS if table == "model_call_projections" else _TOOL_COLUMNS
    updates = _MODEL_UPDATES if table == "model_call_projections" else _TOOL_UPDATES
    row = connection.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({', '.join(['%s'] * len(values))}) "
        "ON CONFLICT (deployment_namespace, session_id, sequence) DO UPDATE SET "
        f"{updates} WHERE {table}.event_id = EXCLUDED.event_id RETURNING event_id",
        values,
    ).fetchone()
    if row is not None:
        return
    existing = connection.execute(
        f"""SELECT event_id FROM {table}
            WHERE deployment_namespace = %s AND session_id = %s AND sequence = %s""",
        values[:3],
    ).fetchone()
    if existing is None or existing["event_id"] != values[3]:
        raise PostgresModelToolProjectionConflictError(
            "projection key conflicts with canonical Event"
        )


_MODEL_COLUMNS = """deployment_namespace, session_id, sequence, event_id, provider,
model_name, input_tokens, estimated_input_tokens, input_token_limit,
input_token_estimate_error, output_tokens, total_tokens, latency_ms, cache_hit,
cost_usd, assistant_message, tool_call_count, created_at"""
_TOOL_COLUMNS = """deployment_namespace, session_id, sequence, event_id, tool_name,
status, idempotency_key, output, artifact_uri, created_at"""
_MODEL_UPDATES = """event_id = EXCLUDED.event_id, provider = EXCLUDED.provider,
model_name = EXCLUDED.model_name, input_tokens = EXCLUDED.input_tokens,
estimated_input_tokens = EXCLUDED.estimated_input_tokens,
input_token_limit = EXCLUDED.input_token_limit,
input_token_estimate_error = EXCLUDED.input_token_estimate_error,
output_tokens = EXCLUDED.output_tokens, total_tokens = EXCLUDED.total_tokens,
latency_ms = EXCLUDED.latency_ms, cache_hit = EXCLUDED.cache_hit,
cost_usd = EXCLUDED.cost_usd, assistant_message = EXCLUDED.assistant_message,
tool_call_count = EXCLUDED.tool_call_count, created_at = EXCLUDED.created_at"""
_TOOL_UPDATES = """event_id = EXCLUDED.event_id, tool_name = EXCLUDED.tool_name,
status = EXCLUDED.status, idempotency_key = EXCLUDED.idempotency_key,
output = EXCLUDED.output, artifact_uri = EXCLUDED.artifact_uri,
created_at = EXCLUDED.created_at"""


def _model_record(event: SessionEvent) -> ModelCallRecord:
    payload = event.payload
    return ModelCallRecord(
        session_id=event.session_id,
        sequence=event.sequence,
        provider=_str(payload, "provider"),
        model_name=_str(payload, "resolved_model") or _str(payload, "model_name"),
        input_tokens=_int(payload, "input_tokens"),
        estimated_input_tokens=_int(payload, "estimated_input_tokens"),
        input_token_limit=_int(payload, "input_token_limit"),
        input_token_estimate_error=_int(payload, "input_token_estimate_error"),
        output_tokens=_int(payload, "output_tokens"),
        total_tokens=_int(payload, "total_tokens"),
        latency_ms=_int(payload, "latency_ms"),
        cache_hit=_cache_hit(payload),
        cost_usd=_float(payload, "cost_usd"),
        assistant_message=str(payload["assistant_message"]),
        tool_call_count=int(payload["tool_call_count"]),
        created_at=event.created_at,
    )


def _tool_record(event: SessionEvent) -> ToolRunRecord:
    metadata = event.payload.get("metadata")
    uri = metadata.get("artifact_uri") if isinstance(metadata, dict) else None
    return ToolRunRecord(
        session_id=event.session_id,
        sequence=event.sequence,
        tool_name=str(event.payload["tool_name"]),
        status=str(event.payload["status"]),
        idempotency_key=event.idempotency_key,
        output=str(event.payload.get("output", "")),
        artifact_uri=uri.strip() if isinstance(uri, str) and uri.strip() else None,
        created_at=event.created_at,
    )


def _model_values(
    namespace: str, event: SessionEvent, record: ModelCallRecord
) -> tuple[object, ...]:
    return (
        namespace,
        event.session_id,
        event.sequence,
        event.event_id,
        record.provider,
        record.model_name,
        record.input_tokens,
        record.estimated_input_tokens,
        record.input_token_limit,
        record.input_token_estimate_error,
        record.output_tokens,
        record.total_tokens,
        record.latency_ms,
        record.cache_hit,
        record.cost_usd,
        record.assistant_message,
        record.tool_call_count,
        record.created_at,
    )


def _tool_values(namespace: str, event: SessionEvent, record: ToolRunRecord) -> tuple[object, ...]:
    return (
        namespace,
        event.session_id,
        event.sequence,
        event.event_id,
        record.tool_name,
        record.status,
        record.idempotency_key,
        record.output,
        record.artifact_uri,
        record.created_at,
    )


def _str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _int(payload: dict[str, object], key: str) -> int | None:
    value = payload.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _bool(payload: dict[str, object], key: str) -> bool | None:
    value = payload.get(key)
    return value if isinstance(value, bool) else None


def _cache_hit(payload: dict[str, object]) -> bool | None:
    explicit = _bool(payload, "cache_hit")
    if explicit is not None:
        return explicit
    tokens = _int(payload, "prompt_cache_hit_tokens")
    return None if tokens is None else tokens > 0


def _float(payload: dict[str, object], key: str) -> float | None:
    value = payload.get(key)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None
