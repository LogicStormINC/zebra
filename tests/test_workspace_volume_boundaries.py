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
