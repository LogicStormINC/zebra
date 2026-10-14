"""Deterministic composition checks; real OCI/PG validation is separate."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_runtime import LocalRuntime, LocalToolGateway
from agent_runtime.deferred import DeferredRuntime
from zebra_agent_config import RuntimeSettings, load_settings
from zebra_agent_worker.execution_runtime import can_defer_runtime
from zebra_agent_worker.worker_tool_gateway import WorkerToolGateway


def _eligibility():
    settings = replace(
        load_settings(env={}),
        profile="cloud",
        runtime=RuntimeSettings(runtime_class="gvisor", defer_provision=True),
    )
    workspace = SimpleNamespace(
        runtime_spec_digest=None, runtime_name=None, snapshot_id=None, snapshot_path=None
    )
    kwargs = dict(
        claimed=SimpleNamespace(recovery=SimpleNamespace(workspace=workspace)),
        binding=object(),
        materialization=object(),
        network_profile="none",
        has_capsule=False,
    )
    return settings, kwargs


def test_defer_requires_explicit_cloud_and_fresh_materialized_attempt() -> None:
    settings, kwargs = _eligibility()
    assert can_defer_runtime(settings, **kwargs)
    for changes in (
        {"profile": "local"},
        {"runtime": replace(settings.runtime, defer_provision=False)},
        {"mcp_servers": (object(),)},
        {"skill_roots": ("/repo",)},
    ):
        assert not can_defer_runtime(replace(settings, **changes), **kwargs)
    for changes in (
        {"binding": None},
        {"materialization": None},
        {"network_profile": "setup-only"},
        {"has_capsule": True},
    ):
        assert not can_defer_runtime(settings, **{**kwargs, **changes})
    workspace = kwargs["claimed"].recovery.workspace
    for field in ("runtime_spec_digest", "runtime_name", "snapshot_id", "snapshot_path"):
        setattr(workspace, field, "existing")
        assert not can_defer_runtime(settings, **kwargs)
        setattr(workspace, field, None)


def test_local_execution_prepares_once_and_management_bypasses(tmp_path: Path) -> None:
    calls = []
    runtime = LocalRuntime()

    def prepare():
        calls.append("prepare")
        return runtime, runtime.provision(workspace_root=str(tmp_path))

    deferred = DeferredRuntime(prepare, ready=lambda _: calls.append("persist"))
    local = LocalToolGateway(tmp_path, runtime=deferred)
    gateway = WorkerToolGateway(local, runtime=deferred)
    assert gateway.model_tools and calls == []
    tool = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.list",
        arguments={},
        created_at=datetime.now(UTC),
    )
    for _ in range(2):
        result = gateway.execute(tool)
        assert result.status is ToolCallStatus.EXECUTED
    assert calls == ["prepare", "persist"]
    gateway.close()
    gateway.close()
    with pytest.raises(RuntimeError, match="closed"):
        deferred.ensure_ready()


def test_message_only_and_management_execute_have_zero_provision(tmp_path: Path) -> None:
    calls = []

    def prepare():
        calls.append("unexpected")
        raise AssertionError("no runtime needed")

    deferred = DeferredRuntime(prepare)
    local = LocalToolGateway(tmp_path, runtime=deferred)
    management = SimpleNamespace(
        execute=lambda call: ToolResult(
            tool_call_id=call.tool_call_id, status=ToolCallStatus.EXECUTED, output="ok"
        )
    )
    gateway = WorkerToolGateway(
        local,
        runtime=deferred,
        management=management,
        management_names=frozenset({"extensions.list"}),
    )
    assert gateway.model_tools and calls == []
    result = gateway.execute(
        ToolCall(
            tool_call_id=new_tool_call_id(),
            name="extensions.list",
            arguments={},
            created_at=datetime.now(UTC),
        )
    )
    assert result.status is ToolCallStatus.EXECUTED
    gateway.close()
    assert calls == []


def test_late_prepare_persists_to_current_recorder(tmp_path: Path, monkeypatch) -> None:
    from agent_core.domain.identifiers import new_session_id
    from zebra_agent_worker import execution_runtime, runtime_setup

    settings, kwargs = _eligibility()
    claimed = kwargs["claimed"]
    claimed.lease = SimpleNamespace(session_id=new_session_id())
    calls = []
    recorders = [
        SimpleNamespace(
            require_active_execution=lambda: None,
            workspace=SimpleNamespace(runtime_spec_digest=None),
        )
    ]
    runtime = LocalRuntime()

    def prepare(*args, **arguments):
        arguments["cancellation_check"]()
        calls.append("prepare")
        return runtime, runtime_setup.PreparedRuntime(
            runtime.provision(workspace_root=str(tmp_path))
        )

    monkeypatch.setattr(runtime_setup, "build_prepared_runtime", prepare)
    monkeypatch.setattr(
        execution_runtime.runtime_authority,
        "persist_runtime_authority",
        lambda recorder, authority, **kw: calls.append(recorder),
    )
    deferred, handle, persisted = execution_runtime.compose_execution_runtime(
        settings,
        tmp_path / "db",
        claimed=claimed,
        task=SimpleNamespace(workspace_root=tmp_path),
        binding=kwargs["binding"],
        materialization=kwargs["materialization"],
        network_profile="none",
        has_capsule=False,
        attempt_number=1,
        created_at=datetime.now(UTC),
        artifact_store=None,
        instance_factory=None,
        compatible_session_ids=(),
        recorder=lambda: recorders[-1],
        trusted_local=False,
    )
    assert isinstance(deferred, DeferredRuntime) and handle is None
    assert not persisted and calls == []
    current = SimpleNamespace(
        require_active_execution=lambda: None, workspace=SimpleNamespace(runtime_spec_digest=None)
    )
    recorders.append(current)
    deferred.ensure_ready()
    assert calls == ["prepare", current]
    deferred.close()


@pytest.mark.parametrize("denied", [False, True])
def test_shared_harness_reply_and_denied_tool_do_not_provision(
    tmp_path: Path, denied: bool
) -> None:
    from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
    from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
    from agent_core.domain.identifiers import new_message_id
    from agent_core.domain.messages import MessageRole, SessionMessage
    from agent_core.domain.modeling import ModelCompletion
    from agent_core.harness import (
        HarnessAttempt,
        HarnessContext,
        HarnessTask,
        SingleAttemptOrchestrator,
    )
    from agent_security import LocalPolicyEngine, PolicyProfile

    calls = []

    def prepare():
        calls.append("unexpected")
        raise AssertionError("reply and denied tools need no sandbox")

    deferred = DeferredRuntime(prepare)
    local = LocalToolGateway(tmp_path, runtime=deferred)
    gateway = WorkerToolGateway(local, runtime=deferred)
    tool = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="patch.apply",
        arguments={"patch": "invalid"},
        created_at=datetime.now(UTC),
    )
    model = ScriptedModelGateway(
        responses=(
            ScriptedModelResponse(
                completion=ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="A reply.",
                        created_at=datetime.now(UTC),
                    ),
                    tool_calls=(tool,) if denied else (),
                )
            ),
        )
    )
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(title="test", user_input="reply", workspace_root=tmp_path)
    )
    orchestrator = SingleAttemptOrchestrator(
        model, LocalPolicyEngine(profile=PolicyProfile.READ_ONLY), gateway
    )
    result = orchestrator.run(
        HarnessContext(
            task=HarnessTask(title="test", user_input="reply", workspace_root=tmp_path),
            session=bootstrap.session,
            attempt=HarnessAttempt(number=1, started_at=datetime.now(UTC)),
        )
    )
    assert result.metadata["model_calls_used"] == 1
    gateway.close()
    assert calls == []
