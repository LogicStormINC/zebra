"""Wave 5 Gate 2 terminal-synthesis evidence-priority tests.

Under the real DSH guard (max_attempts=2) the runtime runs
prepare_terminal_synthesis_evidence FIRST: while completion evidence is
missing and a matching trusted producer exists, the next dispatch is the
typed evidence correction - never validator/no-progress terminal synthesis.
"""

from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
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
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.domain.tools import ToolCall
from agent_runtime import FinosJournalProvider
from agent_storage import (
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from worker_execution_support import _build_execution_service, _created_at
from zebra_agent_worker import SessionRecoveryService


def _scripted_response(content: str, *tool_calls: ToolCall) -> ScriptedModelResponse:
    return ScriptedModelResponse(
        completion=ModelCompletion(
            assistant_message=SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.ASSISTANT,
                content=content,
                created_at=_created_at(),
            ),
            tool_calls=tuple(tool_calls),
            call_metadata=ModelCallMetadata(
                provider="test",
                model_name="test-model",
                usage=ModelUsage(total_tokens=1),
            ),
        )
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
    return bootstrap


class _PolicyAwareScriptedGateway(ScriptedModelGateway):
    def __init__(self, responses) -> None:
        super().__init__(responses)
        self.policies: list[object] = []

    def complete_with_policy(self, messages, *, tools=(), media_inputs=(), invocation_policy=None):
        del media_inputs
        self.policies.append(invocation_policy)
        return self.complete(messages, tools=tools)


class _MixedFinosTransport:
    """Fake FinOS v3 transport: validator returns passed=false; journal reads
    return empty records (the typed evidence label comes from the tool)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def post_json(self, url, *, headers, payload, timeout_seconds):
        del headers, payload, timeout_seconds
        self.calls.append(url)
        if "trade-log-quality:validate" in url:
            return {
                "schema_version": "finos.trade_log_quality.validate.v1",
                "validator_result": {
                    "schema_version": "zebra.validator-result.v1",
                    "passed": False,
                    "issues": [{"code": "fixture_mismatch"}],
                },
            }
        return {"schema_version": "finos.journals.list.v1", "records": []}


_AUTHORITATIVE_READ_TOOLS = {
    "finos.journals.get",
    "finos.journals.list",
    "finos.notes.get",
    "finos.notes.list",
    "finos.positions.list",
    "finos.securities.resolve",
    "finos.snapshots.get",
    "finos.snapshots.list",
    "finos.transactions.list",
}


def _assert_correction_dispatch(gateway, index: int) -> None:
    from agent_core.domain.modeling import ModelInvocationPolicy, ModelToolChoice

    correction_tools = {tool.name for tool in gateway.tool_requests[index]}
    assert "finos.journals.list" in correction_tools
    assert correction_tools <= _AUTHORITATIVE_READ_TOOLS
    assert isinstance(gateway.policies[0], ModelInvocationPolicy)
    assert gateway.policies[0].tool_choice is ModelToolChoice.REQUIRED
    correction_messages = gateway.requests[index]
    assert sum(
        message.metadata.get("missing_completion_evidence") is not None
        for message in correction_messages
    ) == 1
    assert not any(
        message.metadata.get("validator_correction") is True
        for message in correction_messages
    )
    assert not any(
        message.metadata.get("tool_loop_no_progress") is True
        for message in correction_messages
    )
    assert not any(
        "The tool budget is complete." in message.content
        for message in correction_messages
        if message.role is MessageRole.USER
    )


def _assert_single_attempt(database_path: Path, session_id) -> None:
    starts = [
        event
        for event in SQLiteEventStore(database_path).list_for_session(session_id)
        if event.event_type is EventType.HARNESS_ATTEMPT_STARTED
    ]
    assert [event.payload["attempt_sequence"] for event in starts] == [1]


# P1 precedence: validator rejection with missing evidence must produce the
# typed evidence correction dispatch (required tool choice, only matching
# producers, exactly one evidence observation, no terminal guidance).
def test_guarded_validator_evidence_correction_takes_precedence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "wave5-validator-evidence.db"
    bootstrap = _seed_producer_coverage_session(database_path, tmp_path)
    session_id = bootstrap.session.session_id
    provider = FinosJournalProvider(
        base_url="https://finos.internal",
        task_id=str(session_id),
        grant="private-grant",
        contract_version="finos.journals.v3",
        transport=_MixedFinosTransport(),
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_finos_journal_provider",
        lambda settings, database_path, session_id: provider,
    )
    validator_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="finos.trade_log_quality.validate",
        arguments={"report": {"trade_date": "2026-07-29"}},
        created_at=_created_at(),
    )
    producer_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="finos.journals.list",
        arguments={},
        created_at=_created_at(),
    )
    gateway = _PolicyAwareScriptedGateway(
        responses=(
            _scripted_response("Validating the candidate.", validator_call),
            _scripted_response("Collecting the evidence.", producer_call),
            _scripted_response("Final answer."),
        )
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: gateway,
    )

    result = _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="wave5-validator-evidence",
        executed_at=_created_at(),
    )

    assert result.session.status is SessionStatus.COMPLETED
    assert len(gateway.requests) == 3
    _assert_correction_dispatch(gateway, 1)
    assert result.attempt_result.metadata.get("stop_reason") != (
        "attempt_reconstruction_invalid"
    )
    _assert_single_attempt(database_path, session_id)


# P1 precedence: convergence/no-progress with missing evidence must produce
# the typed evidence correction dispatch, not terminal synthesis.
def test_guarded_convergence_evidence_correction_takes_precedence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "wave5-convergence-evidence.db"
    (tmp_path / "stable.txt").write_text("STABLE", encoding="utf-8")
    bootstrap = _seed_producer_coverage_session(database_path, tmp_path)
    session_id = bootstrap.session.session_id
    provider = FinosJournalProvider(
        base_url="https://finos.internal",
        task_id=str(session_id),
        grant="private-grant",
        contract_version="finos.journals.v3",
        transport=_MixedFinosTransport(),
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_finos_journal_provider",
        lambda settings, database_path, session_id: provider,
    )

    def read_call() -> ToolCall:
        return ToolCall(
            tool_call_id=new_tool_call_id(),
            name="files.read",
            arguments={"path": "stable.txt"},
            created_at=_created_at(),
        )

    producer_call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="finos.journals.list",
        arguments={},
        created_at=_created_at(),
    )
    gateway = _PolicyAwareScriptedGateway(
        responses=(
            _scripted_response("Reading the stable file.", read_call()),
            _scripted_response("Reading the stable file again.", read_call()),
            _scripted_response("Reading the stable file again.", read_call()),
            _scripted_response("Reading the stable file again.", read_call()),
            _scripted_response("Collecting the evidence.", producer_call),
            _scripted_response("Final answer."),
        )
    )
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: gateway,
    )

    result = _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="wave5-convergence-evidence",
        executed_at=_created_at(),
    )

    assert result.session.status is SessionStatus.COMPLETED
    assert len(gateway.requests) == 6
    _assert_correction_dispatch(gateway, 4)
    assert result.attempt_result.metadata.get("stop_reason") != (
        "attempt_reconstruction_invalid"
    )
    _assert_single_attempt(database_path, session_id)
