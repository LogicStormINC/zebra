"""Gate A red: a retryable provider failure suspends durably and safely.

W45-GATE-A-04: a provider transport/server error normalized as retryable
(e.g. HTTP 500) that exhausts the configured retry budget must durably leave
the session ``suspended`` (not ``ready``/``running``, not stuck), release the
worker lease, expose only normalized error detail, and remain safely
resumable by a later execution.
"""

import json
from datetime import UTC, datetime

from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCallMetadata,
    ModelCompletion,
    ModelTextDelta,
)
from agent_core.domain.sessions import SessionStatus
from agent_integrations.model_errors import ModelProviderError
from agent_storage import SQLiteEventStore, SQLiteLeaseStore
from worker_execution_support import _build_execution_service, _seed_ready_session


def test_worker_retryable_provider_failure_suspends_safely(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_ready_session(database_path, tmp_path)

    class FailingProviderGateway:
        def complete(self, messages, *, tools=()) -> ModelCompletion:
            raise AssertionError("worker must use the streaming gateway path")

        def complete_stream(self, messages, *, tools=(), on_text_delta) -> ModelCompletion:
            raise ModelProviderError("provider_error", retryable=True, retry_count=0)

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: FailingProviderGateway(),
    )

    result = _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-provider-retryable",
        executed_at=datetime(2026, 8, 13, 6, 31, 12, tzinfo=UTC),
    )

    assert result.session.status is SessionStatus.SUSPENDED
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    assert events[-1].event_type is EventType.SESSION_SUSPENDED
    assert events[-1].payload["reason"] == "model_provider_retry_exhausted"
    serialized = json.dumps(events[-1].payload)
    assert "provider_error" in serialized
    assert "http://" not in serialized and "https://" not in serialized
    assert "packaged provider failure" not in serialized
    assert SQLiteLeaseStore(database_path).get(session_id) is None


def test_worker_retryable_provider_failure_resumes_to_completion(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_ready_session(database_path, tmp_path)
    failures = [0]

    class FlakyProviderGateway:
        def complete(self, messages, *, tools=()) -> ModelCompletion:
            raise AssertionError("worker must use the streaming gateway path")

        def complete_stream(self, messages, *, tools=(), on_text_delta) -> ModelCompletion:
            if failures[0] == 0:
                failures[0] += 1
                raise ModelProviderError("provider_error", retryable=True, retry_count=0)
            on_text_delta(_delta(0, "Recovered."))
            return _completion("Recovered.")

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: FlakyProviderGateway(),
    )
    service = _build_execution_service(database_path)

    suspended = service.execute_session(
        session_id,
        worker_id="worker-provider-retryable",
        executed_at=datetime(2026, 8, 13, 6, 31, 12, tzinfo=UTC),
    )
    assert suspended.session.status is SessionStatus.SUSPENDED

    completed = service.execute_session(
        session_id,
        worker_id="worker-provider-retryable",
        executed_at=datetime(2026, 8, 13, 6, 32, 12, tzinfo=UTC),
    )
    assert completed.session.status is SessionStatus.COMPLETED
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    assert events[-1].event_type is EventType.SESSION_COMPLETED


def _delta(index: int, content: str):
    return ModelTextDelta(index=index, content=content)


def _completion(content: str) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content=content,
            created_at=datetime(2026, 8, 13, 6, 32, 12, tzinfo=UTC),
        ),
        call_metadata=ModelCallMetadata(provider="openai"),
    )
