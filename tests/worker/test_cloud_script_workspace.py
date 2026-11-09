"""Pure containment and factory regression; actual gVisor is opt-in S1."""

from dataclasses import replace
from pathlib import Path

import pytest
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings
from zebra_agent_worker import runtime_factory


def test_script_quota_checks_shared_backing_and_rejects_escape(tmp_path, monkeypatch):
    settings = ZebraAgentSettings(
        profile="test",
        database_url="owned-unused",
        api=ApiSettings(auth_token=None),
        model=ModelSettings("test", "UNSET", "https://unused", "x"),
    )
    settings = replace(
        settings,
        runtime=replace(
            settings.runtime,
            runtime_class="gvisor",
            require_workspace_quota=True,
            image="python@sha256:" + "a" * 64,
        ),
    )
    root = tmp_path / "backing"
    root.mkdir()
    child = root / "owned-script"
    child.mkdir()
    checked = []
    monkeypatch.setenv("ZEBRA_WORKSPACE_VOLUME_ROOT", str(root))
    monkeypatch.setattr(
        runtime_factory, "require_workspace_quota", lambda path, **_: checked.append(Path(path))
    )
    sentinel = object()
    monkeypatch.setattr(runtime_factory, "OciRuntime", lambda *_, **__: sentinel)
    assert runtime_factory.script_workspace_parent(settings) == root
    assert (
        runtime_factory.build_runtime(
            settings, tmp_path, workspace_root=child, network_profile="none"
        )
        is sentinel
    )
    assert checked == [root, root]
    with pytest.raises(ValueError, match="outside"):
        runtime_factory.build_runtime(
            settings, tmp_path, workspace_root=tmp_path, network_profile="none"
        )
