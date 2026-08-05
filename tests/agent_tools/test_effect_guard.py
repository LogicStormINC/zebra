from datetime import UTC, datetime

import pytest
from agent_core.domain.identifiers import new_session_id, new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_storage import EffectReplayRejectedError, SQLiteEffectLedger
from agent_tools import EffectGuardedToolGateway


class _Gateway:
    model_tools = ()
    effective_mcp_tools = ()
    effective_skill_components = ()
    parallel_safe_tools = frozenset()
    parallel_batch_limits = {}

    def __init__(
        self,
        *,
        validator_tools: frozenset[str] = frozenset(),
        read_only_tools: frozenset[str] = frozenset(),
        fail_names: frozenset[str] = frozenset(),
        validation_fail_names: frozenset[str] = frozenset(),
    ) -> None:
        self.calls = 0
        self.validator_tools = validator_tools
        self.read_only_tools = read_only_tools
        self.fail_names = fail_names
        self.validation_fail_names = validation_fail_names

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.calls += 1
        if tool_call.name in self.fail_names:
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                status=ToolCallStatus.FAILED,
                metadata={"reason": "provider_rejected"},
            )
        if tool_call.name in self.validation_fail_names:
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                status=ToolCallStatus.FAILED,
                metadata={"reason": "tool_validation_error"},
            )
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="ok",
        )

    def resolve_model_tool_calls(self, tool_calls: tuple[ToolCall, ...]):
        return tool_calls

    def close(self) -> None:
        pass


def _call(name: str) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments={"command": "deploy"},
        created_at=datetime.now(UTC),
    )


def test_effectful_duplicate_reuses_result_but_read_only_calls_execute(tmp_path) -> None:
    gateway = _Gateway()
    guarded = EffectGuardedToolGateway(
        gateway,
        ledger=SQLiteEffectLedger(tmp_path / "ledger.db"),
        root_session_id=new_session_id(),
        authority_scope="workspace-write",
    )

    first = guarded.execute(_call("command.run"))
    replay = guarded.execute(_call("command.run"))
    guarded.execute(_call("files.read"))
    guarded.execute(_call("files.read"))

    assert replay.output == first.output
    assert gateway.calls == 3


def test_dynamic_validator_bypasses_effect_ledger(tmp_path) -> None:
    gateway = _Gateway(validator_tools=frozenset({"quality.validate"}))
    ledger = SQLiteEffectLedger(tmp_path / "ledger.db")
    root_session_id = new_session_id()
    guarded = EffectGuardedToolGateway(
        gateway,
        ledger=ledger,
        root_session_id=root_session_id,
        authority_scope="workspace-write",
    )

    guarded.execute(_call("quality.validate"))
    guarded.execute(_call("quality.validate"))

    assert gateway.calls == 2
    assert ledger.terminal_keys(root_session_id) == frozenset()


def test_dynamic_read_only_failure_bypasses_ledger_and_executes_again(tmp_path) -> None:
    gateway = _Gateway(
        read_only_tools=frozenset({"provider.records.read"}),
        fail_names=frozenset({"provider.records.read"}),
    )
    ledger = SQLiteEffectLedger(tmp_path / "ledger.db")
    root_session_id = new_session_id()
    guarded = EffectGuardedToolGateway(
        gateway,
        ledger=ledger,
        root_session_id=root_session_id,
        authority_scope="workspace-write",
    )

    first = guarded.execute(_call("provider.records.read"))
    second = guarded.execute(_call("provider.records.read"))

    assert first.status is ToolCallStatus.FAILED
    assert second.status is ToolCallStatus.FAILED
    assert gateway.calls == 2
    assert ledger.has_uncertain(root_session_id) is False
    assert ledger.terminal_keys(root_session_id) == frozenset()


def test_unclassified_failure_marks_uncertain_and_rejects_replay(tmp_path) -> None:
    gateway = _Gateway(fail_names=frozenset({"command.run"}))
    ledger = SQLiteEffectLedger(tmp_path / "ledger.db")
    root_session_id = new_session_id()
    guarded = EffectGuardedToolGateway(
        gateway,
        ledger=ledger,
        root_session_id=root_session_id,
        authority_scope="workspace-write",
    )

    first = guarded.execute(_call("command.run"))

    assert first.status is ToolCallStatus.FAILED
    assert ledger.has_uncertain(root_session_id) is True
    with pytest.raises(EffectReplayRejectedError, match="uncertain"):
        guarded.execute(_call("command.run"))
    assert gateway.calls == 1


def test_emit_declaration_failure_never_marks_uncertain(tmp_path) -> None:
    """artifact.output_contract.emit is a declarative metadata tool with no
    external side effect: even a validation failure (e.g. a malformed
    payload_digest) must not poison the effect ledger, or a later round of a
    stable Task would be blocked by handoff_source_not_quiescent."""
    gateway = _Gateway(fail_names=frozenset({"artifact.output_contract.emit"}))
    ledger = SQLiteEffectLedger(tmp_path / "ledger.db")
    root_session_id = new_session_id()
    guarded = EffectGuardedToolGateway(
        gateway,
        ledger=ledger,
        root_session_id=root_session_id,
        authority_scope="workspace-write",
    )

    first = guarded.execute(_call("artifact.output_contract.emit"))

    assert first.status is ToolCallStatus.FAILED
    assert ledger.has_uncertain(root_session_id) is False
    # A second attempt executes again instead of replaying/blocking.
    guarded.execute(_call("artifact.output_contract.emit"))
    assert gateway.calls == 2


def test_provably_local_failure_marks_failed_no_effect_and_allows_retry(
    tmp_path,
) -> None:
    """A deterministic local failure (validation error) must not poison the
    ledger: the effect settles as failed_no_effect, a later round of the same
    stable Task is not blocked, and the call can be retried."""
    gateway = _Gateway(validation_fail_names=frozenset({"files.read"}))
    ledger = SQLiteEffectLedger(tmp_path / "ledger.db")
    root_session_id = new_session_id()
    guarded = EffectGuardedToolGateway(
        gateway,
        ledger=ledger,
        root_session_id=root_session_id,
        authority_scope="workspace-write",
    )

    first = guarded.execute(_call("files.read"))

    assert first.status is ToolCallStatus.FAILED
    assert ledger.has_uncertain(root_session_id) is False
    guarded.execute(_call("files.read"))
    assert gateway.calls == 2
