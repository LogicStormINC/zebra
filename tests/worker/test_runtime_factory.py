from pathlib import Path

import pytest
from agent_core.ports.runtime import RuntimeClass
from agent_runtime import LocalRuntime, OciRuntime, OsSandboxRuntime
from zebra_agent_config import ApiSettings, ModelSettings, RuntimeSettings, ZebraAgentSettings
from zebra_agent_worker.runtime_factory import build_runtime


def _settings(runtime: RuntimeSettings) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=":memory:",
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="deepseek",
            api_key_env="DEEPSEEK_API_KEY",
            base_url="https://api.deepseek.com",
            model="test",
        ),
        runtime=runtime,
    )


def test_runtime_factory_preserves_trusted_local_compatibility(tmp_path: Path) -> None:
    runtime = build_runtime(
        _settings(RuntimeSettings()),
        tmp_path / "sessions.sqlite",
        workspace_root=tmp_path,
        network_profile="full-trusted-local",
    )

    assert isinstance(runtime, LocalRuntime)


def test_runtime_factory_builds_immutable_gvisor_spec(tmp_path: Path) -> None:
    image = "zebra/runtime@sha256:" + "a" * 64
    runtime = build_runtime(
        _settings(RuntimeSettings(runtime_class="gvisor", image=image, memory_mb=1024)),
        tmp_path / "sessions.sqlite",
        workspace_root=tmp_path,
        network_profile="none",
    )

    assert isinstance(runtime, OciRuntime)
    assert runtime.spec.runtime_class is RuntimeClass.GVISOR
    assert runtime.spec.image == image
    assert runtime.spec.limits.memory_mb == 1024


def test_runtime_factory_builds_native_os_sandbox(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "zebra_agent_worker.runtime_factory.os_sandbox_engine",
        lambda: "sandbox-exec",
    )
    monkeypatch.setattr("agent_runtime.adapters.os_sandbox.platform.system", lambda: "Darwin")

    runtime = build_runtime(
        _settings(RuntimeSettings(runtime_class="os-sandbox")),
        tmp_path / "sessions.sqlite",
        workspace_root=tmp_path,
        network_profile="none",
    )

    assert isinstance(runtime, OsSandboxRuntime)
    assert runtime.spec.image == ""
    assert runtime.spec.engine == "sandbox-exec"


def test_runtime_factory_requires_real_workspace_quota(monkeypatch, tmp_path: Path) -> None:
    checked: list[tuple[Path, int]] = []

    def fake_check(root, *, maximum_bytes):
        checked.append((Path(root), maximum_bytes))

    monkeypatch.setattr(
        "zebra_agent_worker.runtime_factory.require_workspace_quota",
        fake_check,
    )
    build_runtime(
        _settings(RuntimeSettings(require_workspace_quota=True, workspace_quota_mb=8)),
        tmp_path / "sessions.sqlite",
        workspace_root=tmp_path,
        network_profile="full-trusted-local",
    )

    assert checked == [(tmp_path, 8 * 1024 * 1024)]


def test_runtime_factory_fails_closed_when_quota_inspection_fails(
    monkeypatch, tmp_path: Path
) -> None:
    def reject(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("quota unavailable")

    monkeypatch.setattr("zebra_agent_worker.runtime_factory.require_workspace_quota", reject)
    with pytest.raises(RuntimeError, match="quota unavailable"):
        build_runtime(
            _settings(RuntimeSettings(require_workspace_quota=True)),
            tmp_path / "sessions.sqlite",
            workspace_root=tmp_path,
            network_profile="full-trusted-local",
        )
