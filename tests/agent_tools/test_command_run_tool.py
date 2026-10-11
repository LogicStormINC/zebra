import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_runtime import LocalRuntime
from agent_runtime.workspace import LocalWorkspace
from agent_tools import CommandRunTool, ToolExecutor, ToolRegistry
from agent_tools.errors import ToolArgumentError


def _tool_call(arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name="command.run",
        arguments=arguments,
        created_at=datetime(2026, 6, 19, 16, 30, tzinfo=UTC),
    )


def test_command_run_tool_executes_typed_command_in_workspace(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    runtime = LocalRuntime()
    registry = ToolRegistry()
    runner = CommandRunTool(runtime, workspace)
    registry.register(runner.contract, runner.handle)
    executor = ToolExecutor(registry)

    result = executor.execute(
        _tool_call(
            {
                "command": (
                    sys.executable,
                    "-c",
                    "import pathlib; print(pathlib.Path.cwd().name)",
                ),
            }
        )
    )

    assert result.status is ToolCallStatus.EXECUTED
    assert result.output.strip() == tmp_path.name
    assert result.receipt is not None
    assert result.metadata == {
        "command": [sys.executable, "-c", "import pathlib; print(pathlib.Path.cwd().name)"],
        "cwd": ".",
        "exit_code": 0,
        "stderr": "",
        "timed_out": False,
        "failure_reason": None,
        "public_facts": {
            "kind": "operation",
            "tool_call_id": str(result.tool_call_id),
            "operation_completed": True,
            "evidence_basis": "verified_work",
            "receipt": result.receipt.as_metadata(),
            "output_truncated": False,
        },
    }


def test_command_run_tool_captures_non_zero_exit(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    runtime = LocalRuntime()
    registry = ToolRegistry()
    runner = CommandRunTool(runtime, workspace)
    registry.register(runner.contract, runner.handle)
    executor = ToolExecutor(registry)

    result = executor.execute(
        _tool_call(
            {
                "command": (
                    sys.executable,
                    "-c",
                    "import sys; print('boom'); print('bad', file=sys.stderr); sys.exit(7)",
                ),
            }
        )
    )

    assert result.status is ToolCallStatus.FAILED
    assert result.output.strip() == "boom"
    assert result.metadata["exit_code"] == 7
    assert result.metadata["stderr"].strip() == "bad"
    assert result.metadata["timed_out"] is False


def test_command_run_tool_propagates_timeout(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    runtime = LocalRuntime()
    registry = ToolRegistry()
    runner = CommandRunTool(runtime, workspace)
    registry.register(runner.contract, runner.handle)
    executor = ToolExecutor(registry)

    result = executor.execute(
        _tool_call(
            {
                "command": (
                    sys.executable,
                    "-c",
                    "import time; print('start'); time.sleep(0.2)",
                ),
                "timeout_seconds": 0.05,
            }
        )
    )

    assert result.status is ToolCallStatus.FAILED
    assert result.metadata["exit_code"] is None
    assert result.metadata["timed_out"] is True


def test_command_run_tool_rejects_shell_string_arguments(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    runtime = LocalRuntime()
    registry = ToolRegistry()
    runner = CommandRunTool(runtime, workspace)
    registry.register(runner.contract, runner.handle)
    executor = ToolExecutor(registry)

    with pytest.raises(ToolArgumentError, match="list or tuple of strings"):
        executor.execute(_tool_call({"command": "python -c 'print(1)'"}))


def test_command_run_tool_rejects_cwd_outside_workspace(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    runtime = LocalRuntime()
    registry = ToolRegistry()
    runner = CommandRunTool(runtime, workspace)
    registry.register(runner.contract, runner.handle)
    executor = ToolExecutor(registry)

    with pytest.raises(ToolArgumentError, match="must stay within the workspace"):
        executor.execute(
            _tool_call(
                {
                    "command": (sys.executable, "-c", "print('ok')"),
                    "cwd": "../outside",
                }
            )
        )


def test_command_run_tool_accepts_absolute_cwd_inside_workspace(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    workspace = LocalWorkspace(tmp_path)
    runtime = LocalRuntime()
    registry = ToolRegistry()
    runner = CommandRunTool(runtime, workspace)
    registry.register(runner.contract, runner.handle)
    executor = ToolExecutor(registry)

    result = executor.execute(
        _tool_call(
            {
                "command": (sys.executable, "-c", "from pathlib import Path; print(Path.cwd())"),
                "cwd": str(nested),
            }
        )
    )

    assert result.status is ToolCallStatus.EXECUTED
    assert result.output.strip() == str(nested)
    assert result.metadata["cwd"] == "nested"


def test_command_operation_facts_survive_durable_events_and_restore_without_reexecution(
    tmp_path: Path,
) -> None:
    from agent_core.domain.events import EventType, SessionEvent
    from agent_core.domain.sessions import Session
    from agent_core.harness.hooks import NoopVerifier
    from agent_core.harness.models import (
        HarnessAttempt,
        HarnessContext,
        HarnessEventBuffer,
        HarnessEventDraft,
        HarnessTask,
    )
    from agent_core.harness.public_output import ProgressiveEventSink, PublicOutputPolicy
    from agent_core.harness.tool_execution import execute_tool_call
    from agent_storage.sqlite import SQLiteEventStore

    session = Session.create(title="Inspect isolated workspace")
    store_path = tmp_path / "isolated-events.sqlite"
    store = SQLiteEventStore(store_path)
    sequence = 0

    def persist(draft: HarnessEventDraft) -> None:
        nonlocal sequence
        store.append(
            SessionEvent.create(
                session_id=session.session_id,
                sequence=sequence,
                event_type=draft.event_type,
                actor=draft.actor,
                created_at=datetime.now(UTC),
                payload=draft.payload,
            )
        )
        sequence += 1

    runner = CommandRunTool(LocalRuntime(), LocalWorkspace(tmp_path))
    registry = ToolRegistry()
    registry.register(runner.contract, runner.handle)
    call = _tool_call({"command": [sys.executable, "-c", "print('private-stdout-and-argv')"]})
    sink = ProgressiveEventSink(
        persist, user_input="Inspect workspace", policy=PublicOutputPolicy()
    )
    try:
        step = execute_tool_call(
            HarnessContext(
                HarnessTask(title=session.title, user_input="Inspect workspace"),
                session,
                HarnessAttempt(1, datetime.now(UTC)),
            ),
            call,
            tool_gateway=ToolExecutor(registry),
            verifier=NoopVerifier(),
            emitted_events=HarnessEventBuffer(sink),
        )
    finally:
        sink.close()
    assert step.result.receipt is not None
    assert step.result.receipt.tool_name == "command.run"
    assert step.result.receipt.status == "executed"
    assert step.result.receipt.output_bytes == len(step.result.output.encode("utf-8"))
    durable = SQLiteEventStore(store_path).list_for_session(session.session_id)
    terminal_event = next(
        event for event in durable if event.event_type is EventType.TOOL_EXECUTION_COMPLETED
    )
    facts = terminal_event.payload["metadata"]["public_facts"]
    assert facts["receipt"] == step.result.receipt.as_metadata()
    assert facts["tool_call_id"] == str(call.tool_call_id)
    outputs = [event.payload for event in durable if event.event_type is EventType.PUBLIC_OUTPUT]
    evidence = [output for output in outputs if output["phase"] == "evidence"]
    assert len(evidence) == 1 and "evidence_basis" not in evidence[0]
    assert evidence[0]["kind"] == "commentary" and evidence[0]["meaningful"] is False
    assert evidence[0]["evidence_refs"] == [str(call.tool_call_id)]
    assert "private-stdout-and-argv" not in str(outputs) + str(facts)
    assert not any(event.event_type is EventType.ANSWER_COMMITTED for event in durable)
    assert not any(event.event_type is EventType.MODEL_REQUEST_STARTED for event in durable)

    recovered = ProgressiveEventSink(
        persist, user_input="Inspect workspace", policy=PublicOutputPolicy(), prior_outputs=outputs
    )
    try:
        receipt = HarnessEventDraft(
            terminal_event.event_type, terminal_event.actor, terminal_event.payload
        )
        recovered.observe_operation_result(receipt)
        recovered.observe_operation_result(receipt)
    finally:
        recovered.close()
    assert SQLiteEventStore(store_path).list_for_session(session.session_id) == durable
