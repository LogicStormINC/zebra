"""Gate A red: provider rejection classification matrix.

W45-GATE-A-03: the durable terminal classification follows the error's
``retryable`` field:

- ``ModelResponseRejectedError(retryable=False)`` (e.g. streaming
  ``finish_reason=content_filter``) -> durable ``SESSION_FAILED``;
- ``ModelResponseRejectedError(retryable=True)`` after repair exhaustion ->
  durable ``SESSION_SUSPENDED`` (resumable);
- ``ModelProviderError(retryable=False)`` -> durable ``SESSION_FAILED``;
- ``ModelProviderError(retryable=True)`` (HTTP 500/transport) ->
  durable ``SESSION_SUSPENDED`` (resumable).

Every payload carries only normalized error detail (no raw provider message,
URL, or credential) and the worker lease is always released.
"""

import json
from datetime import UTC, datetime

from agent_core.domain.events import EventType
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.sessions import SessionStatus
from agent_core.ports.model_gateway import ModelResponseRejectedError
from agent_integrations.model_errors import ModelProviderError
from agent_storage import SQLiteEventStore, SQLiteLeaseStore
from worker_execution_support import _build_execution_service, _seed_ready_session


def test_worker_provider_failure_is_durable_failed_with_safe_payload(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_ready_session(database_path, tmp_path)

    class FailingProviderGateway:
        def complete(
            self,
            messages,
            *,
            tools=(),
        ) -> ModelCompletion:
            raise AssertionError("worker must use the streaming gateway path")

        def complete_stream(
            self,
            messages,
            *,
            tools=(),
            on_text_delta,
        ) -> ModelCompletion:
            raise ModelProviderError("content_filtered", retryable=False, retry_count=0)

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: FailingProviderGateway(),
    )

    result = _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-provider-fail",
        executed_at=datetime(2026, 8, 13, 6, 31, 12, tzinfo=UTC),
    )

    assert result.session.status is SessionStatus.FAILED
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    assert events[-1].event_type is EventType.SESSION_FAILED
    assert EventType.SESSION_SUSPENDED not in [
        event.event_type for event in events
    ]
    serialized = json.dumps(events[-1].payload)
    assert "content_filtered" in serialized
    assert "http://" not in serialized and "https://" not in serialized
    assert "packaged provider failure" not in serialized
    assert SQLiteLeaseStore(database_path).get(session_id) is None


def test_worker_nonretryable_response_rejection_is_durable_failed(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_ready_session(database_path, tmp_path)

    class RejectingGateway:
        def complete(self, messages, *, tools=()) -> ModelCompletion:
            raise AssertionError("worker must use the streaming gateway path")

        def complete_stream(self, messages, *, tools=(), on_text_delta) -> ModelCompletion:
            raise ModelResponseRejectedError(
                "content_filtered",
                phase="finish_reason",
                retryable=False,
            )

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: RejectingGateway(),
    )

    result = _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-rejected",
        executed_at=datetime(2026, 8, 13, 6, 31, 12, tzinfo=UTC),
    )

    assert result.session.status is SessionStatus.FAILED
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    assert events[-1].event_type is EventType.SESSION_FAILED
    assert events[-1].payload["metadata"]["stop_reason"] == "model_response_rejected"
    assert events[-1].payload["metadata"]["error_message"] == "content_filtered"
    assert SQLiteLeaseStore(database_path).get(session_id) is None


def test_worker_retryable_response_rejection_repair_exhausted_suspends(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_ready_session(database_path, tmp_path)

    class RepairExhaustedGateway:
        def complete(self, messages, *, tools=()) -> ModelCompletion:
            raise AssertionError("worker must use the streaming gateway path")

        def complete_stream(self, messages, *, tools=(), on_text_delta) -> ModelCompletion:
            raise ModelResponseRejectedError(
                "output_truncated",
                phase="finish_reason",
                retryable=True,
            )

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: RepairExhaustedGateway(),
    )

    result = _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-repair-exhausted",
        executed_at=datetime(2026, 8, 13, 6, 31, 12, tzinfo=UTC),
    )

    assert result.session.status is SessionStatus.SUSPENDED
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    assert events[-1].event_type is EventType.SESSION_SUSPENDED
    assert events[-1].payload["reason"] == "model_response_repair_exhausted"
    assert SQLiteLeaseStore(database_path).get(session_id) is None
