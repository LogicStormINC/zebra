from pathlib import Path

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
    monkeypatch.setattr(
        "agent_runtime.adapters.os_sandbox.which",
        lambda _: "/usr/bin/sandbox-exec",
    )

    runtime = build_runtime(
        _settings(RuntimeSettings(runtime_class="os-sandbox")),
        tmp_path / "sessions.sqlite",
        workspace_root=tmp_path,
        network_profile="none",
    )

    assert isinstance(runtime, OsSandboxRuntime)
    assert runtime.spec.image == ""
    assert runtime.spec.engine == "sandbox-exec"
