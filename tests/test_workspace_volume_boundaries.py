"""Allocator/verifier hooks cannot be bypassed by continuation or missing volumes."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from agent_core.domain.workspace_control import WorkspaceLifecycleState
from agent_runtime.workspace_runtime_resolver import WorkspaceRuntimeResolver


def test_new_volume_prepares_before_provision_and_verifies(tmp_path):
    workspace, session = uuid4(), uuid4()
    calls = []
    instance = SimpleNamespace(
        workspace_id=workspace, state=WorkspaceLifecycleState.READY, volume_ref=str(tmp_path)
    )
    provisioner = SimpleNamespace(
        store=SimpleNamespace(get=lambda _: instance),
        provision_existing=lambda _: calls.append("provision") or instance,
    )
    resolver = WorkspaceRuntimeResolver(
        provisioner,
        prepare_volume=lambda w, s: calls.append(("prepare", w, s)),
        verify_volume=lambda w, s, p: calls.append(("verify", w, s, p)),
    )
    assert resolver.resolve("workspace://" + str(workspace), session_id=session) == tmp_path
    assert calls == [
        ("prepare", workspace, session),
        "provision",
        ("verify", workspace, session, tmp_path),
    ]
    calls.clear()
    assert resolver.resolve_ready("workspace://" + str(workspace), session_id=session) == tmp_path
    assert calls == [("verify", workspace, session, tmp_path)]


def test_failed_allocation_never_materializes():
    provisioner = Mock()

    def refuse(*_):
        raise ValueError("quota unavailable")

    resolver = WorkspaceRuntimeResolver(provisioner, prepare_volume=refuse)
    with pytest.raises(ValueError, match="quota unavailable"):
        resolver.resolve("workspace://" + str(uuid4()), session_id=uuid4())
    provisioner.provision_existing.assert_not_called()


def test_resume_rechecks_volume_quota(tmp_path):
    workspace, session = uuid4(), uuid4()
    instance = SimpleNamespace(
        workspace_id=workspace, state=WorkspaceLifecycleState.SEALED, volume_ref=str(tmp_path)
    )
    provisioner = Mock()
    provisioner.store.get.return_value = instance

    def refuse(*_):
        raise ValueError("mount identity changed")

    resolver = WorkspaceRuntimeResolver(provisioner, verify_volume=refuse)
    with pytest.raises(ValueError, match="mount identity changed"):
        resolver.resolve_ready("workspace://" + str(workspace), session_id=session)
    provisioner.provision_existing.assert_not_called()


def test_local_paths_remain_local():
    resolver = WorkspaceRuntimeResolver(
        Mock(), prepare_volume=lambda *_: pytest.fail("unexpected allocation")
    )
    assert resolver.resolve("/local/work", session_id=uuid4()) == Path("/local/work")


@pytest.mark.parametrize("reference", ["workspace://", "workspace:/"])
def test_ordinary_task_uses_control_plane_resolver(tmp_path, reference):
    from agent_core.domain.tool_profiles import ToolProfile
    from agent_security import parse_network_profile
    from zebra_agent_worker.bundle_assembly import resolve_bound_workspace
    from zebra_agent_worker.task_recovery import RecoveredTask

    task = RecoveredTask(
        title="Ordinary Host task", user_input="Read the attached file",
        workspace_root=Path(reference + str(uuid4())), policy_profile="read_only",
        tool_profile=ToolProfile.RESEARCH, network_profile=parse_network_profile("none"),
        mcp_allowlist=None, skill_components=None, history_session_ids=None,
        max_attempts=1, max_model_calls=1, max_tool_calls=1, attachments=(),
        runtime_evidence=(), host_context=None, definition_snapshot=None,
    )
    resolver = Mock()
    resolver.resolve.return_value = tmp_path
    session = uuid4()
    resolved = resolve_bound_workspace(task, resolver, session)
    assert resolved.workspace_root == tmp_path
    assert task.workspace_root != tmp_path
    resolver.resolve.assert_called_once_with(str(task.workspace_root), session_id=session)
    resolver.resolve.side_effect = ValueError("unverified physical quota")
    from zebra_agent_worker.execution_finalization import RetryableWorkerSetupError
    with pytest.raises(RetryableWorkerSetupError):
        resolve_bound_workspace(task, resolver, session)
