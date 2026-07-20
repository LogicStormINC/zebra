from datetime import UTC, datetime

from agent_core.domain.identifiers import new_session_id, new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_storage import SQLiteEffectLedger
from agent_tools import EffectGuardedToolGateway


class _Gateway:
    model_tools = ()
    effective_mcp_tools = ()
    effective_skill_components = ()
    parallel_safe_tools = frozenset()
    parallel_batch_limits = {}

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.calls += 1
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
