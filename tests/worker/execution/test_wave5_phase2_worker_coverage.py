"""Wave 5 Phase 2 hosted-worker coverage scenarios (ZNX-WAVE5-OUTER-ATTEMPTS-01).

Hosted Worker behavior for the typed-tool-only correction contract: no
matching advertised trusted producer never dispatches a prompt-only
correction; a genuine trusted producer yields one typed correction per
Attempt and the exact after-correction retry code; tampered runtime guidance
fails closed before the gateway; the public projection carries only the safe
coverage verdict.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.agent_definitions import (
    AgentDefinition,
    CompletionEvidenceContract,
    CompletionEvidenceRequirement,
)
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCallMetadata,
    ModelCompletion,
    ModelUsage,
)
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.domain.tools import ToolCall
from agent_storage import (
    FinosJournalGrant,
    SQLiteAgentTaskStore,
    SQLiteEventStore,
    SQLiteFinosJournalGrantStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from test_wave5_phase2_coverage_correction import _financial_definition
from worker_execution_support import _build_execution_service, _created_at, _settings
from zebra_agent_config import FinosJournalProviderSettings
from zebra_agent_worker import SessionRecoveryService


class _AlwaysAssistantGateway:
    provider = "test"
    model_name = "test-model"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, *, tools=(), media_inputs=()):
        del tools, media_inputs
        self.calls += 1
        return _assistant_completion("No typed evidence is available.")


def _assistant_completion(content: str) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content=content,
            created_at=_created_at(),
        ),
        call_metadata=ModelCallMetadata(
            provider="test",
            model_name="test-model",
            usage=ModelUsage(total_tokens=1),
        ),
    )


class _PolicyAwareWrongToolGateway:
    """Policy-aware gateway: the typed correction dispatch is forced to call
    the required producer, but the model responds with an unadvertised-for-
    correction tool so the bounded correction is consumed without evidence."""

    provider = "test"
    model_name = "test-model"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, *, tools=(), media_inputs=()):
        del tools, media_inputs
        self.calls += 1
        return _assistant_completion("No typed evidence is available.")

    def complete_with_policy(self, messages, *, tools=(), media_inputs=(), invocation_policy):
        del media_inputs, invocation_policy
        self.calls += 1
        return ModelCompletion(
            assistant_message=SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.ASSISTANT,
                content="Calling the wrong tool during the correction.",
                created_at=_created_at(),
            ),
            tool_calls=(
                ToolCall(
                    tool_call_id=new_tool_call_id(),
                    name="files.read",
                    arguments={"path": "irrelevant.txt"},
                    created_at=_created_at(),
                ),
            ),
            call_metadata=ModelCallMetadata(
                provider="test",
                model_name="test-model",
                usage=ModelUsage(total_tokens=1),
            ),
        )


def _authoritative_definition() -> AgentDefinition:
    return AgentDefinition(
        agent_id="agent-neutral",
        version="1.0.0",
        completion_contract=CompletionEvidenceContract(
            required_evidence=(
                CompletionEvidenceRequirement(
                    evidence_id="authoritative_financial",
                    typed_evidence=("authoritative_typed_read",),
                ),
            )
        ),
    )


def _seed_coverage_session(database_path: Path, workspace_root: Path):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Queued coverage task",
            user_input="Complete the analysis.",
            workspace_root=workspace_root.resolve(),
            tool_profile=ToolProfile.CODING,
            max_attempts=2,
            max_corrections_per_attempt=1,
            agent_definition=_financial_definition(),
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    SessionRecoveryService(
        event_store,
        SQLiteProjectionStore(database_path),
        SQLiteWorkspaceProjectionStore(database_path),
    ).recover_session(bootstrap.session.session_id)
    return bootstrap


def _seed_producer_coverage_session(database_path: Path, workspace_root: Path):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Queued coverage task",
            user_input="Complete the analysis.",
            workspace_root=workspace_root.resolve(),
            tool_profile=ToolProfile.CODING,
            max_attempts=2,
            max_corrections_per_attempt=1,
            agent_definition=_authoritative_definition(),
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    SessionRecoveryService(
        event_store,
        SQLiteProjectionStore(database_path),
        SQLiteWorkspaceProjectionStore(database_path),
    ).recover_session(bootstrap.session.session_id)
    task = SQLiteAgentTaskStore(database_path).ensure_for_session(
        bootstrap.session.session_id
    )
    SQLiteFinosJournalGrantStore(database_path).bind(
        FinosJournalGrant(
            task_id=task.task_id,
            contract_version="finos.journals.v1",
            grant="private-grant",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    return bootstrap


def _producer_settings(database_path: Path):
    return replace(
        _settings(database_path),
        finos_journal_provider=FinosJournalProviderSettings(
            base_url="https://finos.internal"
        ),
    )


# P1-3 / P2-9: with required typed evidence but NO matching currently-
# advertised trusted producer, the hosted worker must not dispatch a
# prompt-only correction: one initial model call only, legacy non-retryable
# code, and no Attempt 2.
def test_hosted_worker_without_producer_never_dispatches_correction(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "wave5-p2-9.db"
    bootstrap = _seed_coverage_session(database_path, tmp_path)
    session_id = bootstrap.session.session_id
    gateway = _AlwaysAssistantGateway()
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: gateway,
    )

    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="wave5-p2-9",
        executed_at=_created_at(),
    )

    events = SQLiteEventStore(database_path).list_for_session(session_id)
    starts = [
        event
        for event in events
        if event.event_type is EventType.HARNESS_ATTEMPT_STARTED
    ]
    assert [event.payload["attempt_sequence"] for event in starts] == [1]
    outcomes = [
        event
        for event in events
        if event.event_type is EventType.ATTEMPT_OUTCOME_RECORDED
    ]
    assert [event.payload["retry_scheduled"] for event in outcomes] == [False]
    failed = next(event for event in events if event.event_type is EventType.SESSION_FAILED)
    assert failed.payload["attempt_number"] == 1
    assert failed.payload["metadata"]["stop_reason"] == (
        "completion_evidence_missing"
    )
    assert failed.payload["retryable"] is False
    verdict = failed.payload["coverage_verdict"]
    assert verdict["status"] == "missing"
    assert verdict["required_count"] == 1
    assert verdict["satisfied_count"] == 0
    assert verdict["missing_count"] == 1
    assert "authoritative_financial" not in verdict["message"]
    assert gateway.calls == 1


# P2-9b: with a genuine trusted advertised producer, one typed correction per
# Attempt may still miss coverage, yielding the exact after-correction code
# and Attempt 2; retry exhaustion terminals with the safe coverage verdict.
def test_hosted_worker_exhausts_coverage_retry_with_typed_producer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "wave5-p2-9b.db"
    bootstrap = _seed_producer_coverage_session(database_path, tmp_path)
    session_id = bootstrap.session.session_id
    gateway = _PolicyAwareWrongToolGateway()
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: gateway,
    )

    _build_execution_service(
        database_path, settings=_producer_settings(database_path)
    ).execute_session(
        session_id,
        worker_id="wave5-p2-9b",
        executed_at=_created_at(),
    )

    events = SQLiteEventStore(database_path).list_for_session(session_id)
    starts = [
        event
        for event in events
        if event.event_type is EventType.HARNESS_ATTEMPT_STARTED
    ]
    assert [event.payload["attempt_sequence"] for event in starts] == [1, 2]
    outcomes = [
        event
        for event in events
        if event.event_type is EventType.ATTEMPT_OUTCOME_RECORDED
    ]
    assert [event.payload["retry_scheduled"] for event in outcomes] == [True, False]
    assert [event.payload["terminal_reason"] for event in outcomes] == [
        "completion_evidence_missing_after_correction",
        "completion_evidence_missing_after_correction",
    ]
    failed = next(event for event in events if event.event_type is EventType.SESSION_FAILED)
    assert failed.payload["attempt_number"] == 2
    assert failed.payload["metadata"]["stop_reason"] == (
        "completion_evidence_missing_after_correction"
    )
    assert failed.payload["retryable"] is False
    verdict = failed.payload["coverage_verdict"]
    assert verdict["status"] == "missing"
    assert verdict["required_count"] == 1
    assert verdict["satisfied_count"] == 0
    assert verdict["missing_count"] == 1
    assert "authoritative_financial" not in verdict["message"]
    assert gateway.calls == 4  # initial + one typed correction per Attempt


# P1-2: tampered runtime guidance (content or metadata) must fail closed at the
# pre-gateway reconstruction guard with zero additional gateway calls, while
# the honest observation dispatches (covered by P2-9b).
@pytest.mark.parametrize("tamper", ("content", "metadata"))
def test_tampered_runtime_guidance_fails_closed_before_gateway(
    tmp_path: Path,
    monkeypatch,
    tamper: str,
) -> None:
    from agent_core.harness.completion_blocking import (
        append_missing_evidence_observation as _real_append,
    )

    def tampered_append(
        messages,
        *,
        missing,
        open_plan_steps,
        definition,
        trusted_evidence_tools,
        created_at,
    ):
        tools = _real_append(
            messages,
            missing=missing,
            open_plan_steps=open_plan_steps,
            definition=definition,
            trusted_evidence_tools=trusted_evidence_tools,
            created_at=created_at,
        )
        if tamper == "content":
            messages[-1] = messages[-1].model_copy(update={"content": "PRIVATE OVERRIDE"})
        else:
            messages[-1] = messages[-1].model_copy(
                update={
                    "metadata": {
                        "missing_completion_evidence": ["injected"],
                        "attacker": True,
                    }
                }
            )
        return tools

    monkeypatch.setattr(
        "agent_core.harness.completion_blocking.append_missing_evidence_observation",
        tampered_append,
    )
    database_path = tmp_path / f"wave5-p2-9c-{tamper}.db"
    bootstrap = _seed_producer_coverage_session(database_path, tmp_path)
    session_id = bootstrap.session.session_id
    gateway = _PolicyAwareWrongToolGateway()
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: gateway,
    )

    _build_execution_service(
        database_path, settings=_producer_settings(database_path)
    ).execute_session(
        session_id,
        worker_id=f"wave5-p2-9c-{tamper}",
        executed_at=_created_at(),
    )

    assert gateway.calls == 1  # initial dispatch only; tampered correction blocked
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    failed = next(event for event in events if event.event_type is EventType.SESSION_FAILED)
    assert failed.payload["metadata"]["stop_reason"] == "attempt_reconstruction_invalid"
    starts = [
        event
        for event in events
        if event.event_type is EventType.HARNESS_ATTEMPT_STARTED
    ]
    assert [event.payload["attempt_sequence"] for event in starts] == [1]


# P2-10: the public projection carries only the safe coverage verdict; private
# requirement IDs, evidence refs, digests and diagnostics never become public.
def test_public_projection_exposes_only_safe_coverage_verdict(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from agent_core.application.public_conversation import project_public_conversation
    from agent_storage import SQLiteAgentTaskStore
    from zebra_agent_api.task_final_identity import final_message_identity

    database_path = tmp_path / "wave5-p2-10.db"
    bootstrap = _seed_coverage_session(database_path, tmp_path)
    session_id = bootstrap.session.session_id
    gateway = _AlwaysAssistantGateway()
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: gateway,
    )
    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="wave5-p2-10",
        executed_at=_created_at(),
    )
    task_store = SQLiteAgentTaskStore(database_path)
    task = task_store.ensure_for_session(session_id)
    task_events = task_store.read_events(task.task_id, -1)

    projection = project_public_conversation(task.task_id, task_events)
    final_items = [item for item in projection.items if item.role == "final_response"]
    assert final_items == []
    failure_items = [item for item in projection.items if item.role == "failure"]
    assert len(failure_items) == 1
    assert failure_items[0].data["retryable"] is False
    verdict = failure_items[0].data["coverage_verdict"]
    assert set(verdict) == {
        "status",
        "required_count",
        "satisfied_count",
        "missing_count",
        "message",
    }
    assert final_message_identity(database_path, str(task.task_id)) is None
    leaked = {
        key
        for item in projection.items
        for key in (*item.data, item.content)
        if "authoritative_financial" in str(key)
        or "sha256:" in str(key)
        or "completion_evidence_missing" in str(key)
    }
    assert leaked == set()
