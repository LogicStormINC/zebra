"""Cloud lifecycle is mandatory while local factory compatibility is retained."""

from dataclasses import replace

import pytest
from zebra_agent_config import RuntimeSettings
from zebra_agent_worker.runtime_factory import build_runtime

from tests.worker.test_runtime_factory import _settings


def test_cloud_factory_without_fenced_instance_dependency_fails_before_engine(tmp_path):
    settings = replace(
        _settings(
            RuntimeSettings(runtime_class="gvisor", image="zebra/runtime@sha256:" + "a" * 64)
        ),
        profile="cloud",
    )
    with pytest.raises(ValueError, match="fenced instance lifecycle"):
        build_runtime(
            settings, tmp_path / "unused.db", workspace_root=tmp_path, network_profile="none"
        )


def test_cloud_factory_passes_pinned_engine_identity_to_injected_factory(tmp_path, monkeypatch):
    from tests.agent_runtime.test_oci_instances import ExactEngine, Lifecycle

    engine, lifecycle = ExactEngine(), Lifecycle()
    engine.identity = "a" * 64
    monkeypatch.setattr("zebra_agent_worker.runtime_factory.PinnedOciEngine", lambda _: engine)
    settings = replace(
        _settings(
            RuntimeSettings(runtime_class="gvisor", image="zebra/runtime@sha256:" + "a" * 64)
        ),
        profile="cloud",
    )
    requested = []

    def factory(identity):
        requested.append(identity)
        return lifecycle

    runtime = build_runtime(
        settings,
        tmp_path / "unused.db",
        workspace_root=tmp_path,
        network_profile="none",
        instance_factory=factory,
    )
    handle = runtime.provision()
    assert requested == [engine.identity]
    assert lifecycle.reservations[0][0] == handle.handle_id
    assert not any("ps" in call for call in engine.calls)
