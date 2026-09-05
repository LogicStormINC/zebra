"""No cloud session sweep; uncertain creation and exact cleanup retain identity."""

import json
from subprocess import CompletedProcess, TimeoutExpired

import pytest
from agent_core.ports.runtime import RuntimeCapabilityError
from agent_runtime import OciRuntime

from tests.agent_runtime.test_oci_runtime import FakeEngine, _spec


class Lifecycle:
    engine_identity = "a" * 64

    def __init__(self):
        self.reservations = []
        self.created_ids = []
        self.removed_ids = []
        self.revoked = False
        self.fail_record = False

    def reserve(self, instance, session, digest):
        self.reservations.append((instance, session, digest))
        return {"zebra.agent.scope": "trusted-scope"}

    def created(self, instance, container):
        if self.fail_record:
            raise RuntimeError("synthetic DB unavailable")
        self.created_ids.append((instance, container))

    def authorize(self, instance, container):
        if self.revoked:
            raise RuntimeError("revoked")

    def removed(self, instance, container):
        if (instance, container) not in self.created_ids:
            raise RuntimeError("unsettled creation")
        self.removed_ids.append((instance, container))


class ExactEngine(FakeEngine):
    def __init__(self):
        super().__init__()
        self.metadata = {}
        self.fail_rm = False
        self.on_create = lambda: None

    def __call__(self, command, **kwargs):
        result = super().__call__(command, **kwargs)
        if "create" in command:
            container = f"{len(self.metadata) + 1:064x}"
            self.metadata[container] = {
                "Id": container,
                "Name": command[command.index("--name") + 1],
                "Config": {
                    "Labels": dict(
                        command[i + 1].split("=", 1)
                        for i, v in enumerate(command)
                        if v == "--label"
                    )
                },
            }
            self.on_create()
            return CompletedProcess(command, 0, container, "")
        if "inspect" in command:
            return CompletedProcess(command, 0, json.dumps(self.metadata[command[-1]]), "")
        if "rm" in command and self.fail_rm:
            return CompletedProcess(command, 1, "", "synthetic failure")
        return result


def test_double_provision_is_two_instances_without_session_sweep(tmp_path):
    engine, lifecycle = ExactEngine(), Lifecycle()
    runtime = OciRuntime(_spec(tmp_path), runner=engine, instance_lifecycle=lifecycle)
    first, second = runtime.provision(), runtime.provision()
    assert first.handle_id != second.handle_id
    assert len(lifecycle.reservations) == 2
    assert {row[2] for row in lifecycle.reservations} == {runtime.spec.digest}
    assert not any("ps" in call or "rm" in call for call in engine.calls)
    with pytest.raises(RuntimeCapabilityError, match="exact runtime"):
        runtime.destroy_session(runtime.spec.session_id)
    runtime.close()
    assert len(lifecycle.removed_ids) == 2


def test_revocation_during_create_prevents_start_and_removes_exact_instance(tmp_path):
    engine, lifecycle = ExactEngine(), Lifecycle()
    engine.on_create = lambda: setattr(lifecycle, "revoked", True)
    runtime = OciRuntime(_spec(tmp_path), runner=engine, instance_lifecycle=lifecycle)
    with pytest.raises(RuntimeError, match="revoked"):
        runtime.provision()
    assert not any("start" in call for call in engine.calls)
    assert lifecycle.created_ids == lifecycle.removed_ids


def test_lost_create_record_is_not_falsely_settled(tmp_path):
    engine, lifecycle = ExactEngine(), Lifecycle()
    lifecycle.fail_record = True
    runtime = OciRuntime(_spec(tmp_path), runner=engine, instance_lifecycle=lifecycle)
    with pytest.raises(RuntimeError):
        runtime.provision()
    assert len(lifecycle.reservations) == 1 and not lifecycle.removed_ids
    assert not any("start" in call for call in engine.calls)
    assert len(runtime._handles) == 1


@pytest.mark.parametrize("tracked", [False, True])
def test_failed_remove_retains_handle_for_retry(tmp_path, tracked):
    engine, lifecycle = ExactEngine(), Lifecycle()
    runtime = OciRuntime(
        _spec(tmp_path), runner=engine, instance_lifecycle=lifecycle if tracked else None
    )
    handle = runtime.provision()
    engine.fail_rm = True
    with pytest.raises(RuntimeCapabilityError):
        runtime.destroy(handle)
    assert handle.handle_id in runtime._handles
    engine.fail_rm = False
    runtime.destroy(handle)
    assert handle.handle_id not in runtime._handles


@pytest.mark.parametrize(
    "field", ["zebra.agent.scope", "zebra.agent.engine", "zebra.agent.instance"]
)
def test_label_conflict_does_not_remove_victim(tmp_path, field):
    engine, lifecycle = ExactEngine(), Lifecycle()
    runtime = OciRuntime(_spec(tmp_path), runner=engine, instance_lifecycle=lifecycle)
    handle = runtime.provision()
    engine.metadata[f"{1:064x}"]["Config"]["Labels"][field] = "other"
    with pytest.raises(RuntimeCapabilityError, match="identity"):
        runtime.destroy(handle)
    assert not any("rm" in call for call in engine.calls)


def test_create_timeout_keeps_reservation_and_has_safe_error(tmp_path):
    engine, lifecycle = ExactEngine(), Lifecycle()

    def timeout(command, **kwargs):
        if "create" in command:
            assert kwargs["timeout"] == 30
            raise TimeoutExpired(command, 30, stderr="synthetic-secret")
        return engine(command, **kwargs)

    runtime = OciRuntime(_spec(tmp_path), runner=timeout, instance_lifecycle=lifecycle)
    with pytest.raises(RuntimeCapabilityError, match="timed out") as error:
        runtime.provision()
    assert "synthetic-secret" not in str(error.value)
    assert len(lifecycle.reservations) == 1 and not lifecycle.removed_ids


def test_actual_setup_phase_uses_two_instance_reservations(tmp_path):
    from hashlib import sha256

    from agent_runtime import SetupPhasePlan, SetupPhaseRunner
    from agent_security import SetupDownload, SetupEgressGateway

    engine, lifecycle = ExactEngine(), Lifecycle()
    (tmp_path / "uv.lock").write_text("locked")
    runtime = OciRuntime(_spec(tmp_path), runner=engine, instance_lifecycle=lifecycle)
    result = SetupPhaseRunner(
        SetupPhasePlan(
            command=("true",),
            dependencies=(
                SetupDownload(
                    url="https://packages.example/wheel",
                    sha256=sha256(b"wheel").hexdigest(),
                    file_name="wheel",
                ),
            ),
            lockfiles=("uv.lock",),
        ),
        SetupEgressGateway(
            allowed_domains=("packages.example",),
            cache_root=tmp_path / "cache",
            transport=lambda *_, **kwargs: b"wheel",
        ),
    ).run(runtime, workspace_root=tmp_path)
    assert len(lifecycle.reservations) == 2
    assert lifecycle.reservations[0][0] != result.agent_handle.handle_id
    assert lifecycle.reservations[1][0] == result.agent_handle.handle_id
    assert len(lifecycle.removed_ids) == 1


def test_remove_settlement_failure_retries_without_forgetting_engine_success(tmp_path, monkeypatch):
    engine, lifecycle = ExactEngine(), Lifecycle()
    runtime = OciRuntime(_spec(tmp_path), runner=engine, instance_lifecycle=lifecycle)
    handle = runtime.provision()
    original = lifecycle.removed
    monkeypatch.setattr(lifecycle, "removed", lambda *_: (_ for _ in ()).throw(RuntimeError("DB")))
    with pytest.raises(RuntimeError):
        runtime.destroy(handle)
    assert handle.handle_id in runtime._handles
    monkeypatch.setattr(lifecycle, "removed", original)
    engine.metadata.clear()  # successful engine removal is not a future lookup hint
    runtime.destroy(handle)
    assert len([call for call in engine.calls if "rm" in call]) == 1
