"""Bounded exact engine observations, never infer absence from an engine failure."""

import json
from dataclasses import replace
from subprocess import CompletedProcess, TimeoutExpired
from uuid import uuid4

import pytest
from agent_runtime import command_runtime_cleanup as runtime
from agent_storage.postgres.command_runtime_cleanup import CleanupClaim, CleanupTarget


def _target(container="a" * 64):
    instance = uuid4()
    return CleanupTarget(
        instance,
        container,
        f"zebra-{instance}",
        (("zebra.agent.instance", str(instance)), ("zebra.agent.scope", "trusted")),
    )


class Engine:
    identity = "e" * 64

    def __init__(self, target, *, present=True, wrong=False, fail=None):
        self.target, self.present, self.wrong, self.fail = target, present, wrong, fail
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        assert 0 < kwargs["timeout"] <= 10
        operation = command[1]
        if self.fail == operation:
            return CompletedProcess(command, 1, "", "synthetic credential")
        if self.fail == "timeout":
            raise TimeoutExpired(command, 10, stderr="synthetic credential")
        container = self.target.container_id or "b" * 64
        output = ""
        if operation == "ps":
            output = container if self.present else ""
        elif operation == "inspect":
            output = json.dumps(
                {
                    "Id": container,
                    "Name": self.target.container_name,
                    "Config": {"Labels": {} if self.wrong else dict(self.target.labels)},
                }
            )
        return CompletedProcess(command, 0, output, "")


@pytest.mark.parametrize(
    "known,present", [(True, True), (True, False), (False, True), (False, False)]
)
def test_positive_lookup_distinguishes_known_absence_from_unsettled_creation(known, present):
    target = _target("a" * 64 if known else None)
    engine = Engine(target, present=present)
    container, error = runtime._remove_exact(engine, "docker", target, 10)
    if not known and not present:
        assert (container, error) == (None, "creation_unsettled")
    else:
        assert error is None and len(container) == 64
    removals = [call for call in engine.calls if call[1] == "rm"]
    assert len(removals) == int(present)
    assert all(call[-1] == container for call in removals)


@pytest.mark.parametrize("failure", ["ps", "inspect", "rm", "timeout"])
def test_engine_errors_are_not_absence_or_raw_persisted_errors(failure):
    target = _target()
    engine = Engine(target, fail=failure)
    result = runtime._remove_exact(engine, "docker", target, 10)
    assert result == (None, "engine_unavailable")
    assert "credential" not in str(result)


def test_conflicting_labels_never_delete():
    target = _target()
    engine = Engine(target, wrong=True)
    assert runtime._remove_exact(engine, "docker", target, 10) == (
        None,
        "instance_identity_conflict",
    )
    assert not any(call[1] == "rm" for call in engine.calls)


def test_tick_is_bounded_and_engine_runs_between_claim_and_settlement(monkeypatch):
    target = _target()
    engine = Engine(target)
    claim = CleanupClaim("namespace", uuid4(), uuid4(), "owner", 1, engine.identity, target)
    history = []

    def acquire(*args, **kwargs):
        history.append("claim_committed")
        assert history[-2:-1] in ([], ["settled"])
        return claim

    def settle(*args, **kwargs):
        assert engine.calls[-1][1] == "rm"
        history.append("settled")
        return True

    monkeypatch.setattr(runtime, "claim_runtime_cleanup", acquire)
    monkeypatch.setattr(runtime, "settle_runtime_cleanup", settle)
    assert (
        runtime.cleanup_runtime_batch(
            "unused", deployment_namespace="namespace", owner="owner", engine=engine, batch_size=2
        )
        == 2
    )
    assert history == ["claim_committed", "settled", "claim_committed", "settled"]


@pytest.mark.parametrize("value", [True, 0, 33])
def test_invalid_batch_rejected_before_any_database_or_engine_io(value):
    engine = Engine(_target())
    with pytest.raises(ValueError):
        runtime.cleanup_runtime_batch(
            "unused",
            deployment_namespace="namespace",
            owner="owner",
            engine=engine,
            batch_size=value,
        )
    assert engine.calls == []


def test_short_id_metadata_is_never_accepted():
    target = replace(_target(), container_id="short")
    engine = Engine(target)
    assert runtime._remove_exact(engine, "docker", target, 10)[1] == "instance_identity_conflict"
    assert not any(call[1] == "rm" for call in engine.calls)
