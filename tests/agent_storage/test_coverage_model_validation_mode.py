"""Pure orchestration regressions; native integrity and object proof are separate gates."""

from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_core.domain.coverage_model_budget import (
    CoverageModelBudgetState,
    CoverageModelPolicy,
    CoverageModelUsageReceipt,
)
from agent_storage.postgres import coverage_model_budget as budget
from agent_storage.postgres import coverage_model_source as source

from tests.agent_core.test_coverage_model_budget import reservation
from tests.agent_core.test_coverage_task_admission import NOW


@pytest.fixture(params=["eager", "final_certification"])
def env(request, monkeypatch):
    mode = request.param
    policy = CoverageModelPolicy(
        admission_event_digest="a" * 64, admission_digest="a" * 64,
        task_binding_digest="b" * 64, model_profile="review", max_calls=10,
        max_tokens=1000, max_runtime_seconds=60, started_at=NOW,
        deadline=NOW + timedelta(seconds=60),
        **({"validation_mode": mode} if mode != "eager" else {}),
    )
    state = CoverageModelBudgetState(policy=policy, calls=1, charged_tokens=3, unresolved=0)
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = {"result": None}
    store = budget.CoverageModelBudgetQueries()
    store._database = SimpleNamespace(
        _dsn="postgresql://fixture", deployment_namespace="deployment",
        connect=lambda: nullcontext(connection),
    )
    store._deployment = "deployment"
    store._supported_model_profiles = frozenset({"review"})
    store._artifacts = object()
    binding = SimpleNamespace(namespace="namespace", run_id="run")
    mocks = {}
    for name, result in {
        "lock_run": ({"cancelled": False}, 10),
        "assert_projection": None, "assert_not_certified": None,
        "validate_write": (NOW, policy.task_binding_digest, None),
        "validate_reservation": None, "task_policy": policy,
        "indexed_state": state, "indexed_call": None,
        "preflight_original_volume": None, "verify_settled_checkpoints": None,
        "verify_model_checkpoint": b"checkpoint", "checkpoint_source": None,
        "check_checkpoint_retention": None,
        "append_coverage_event": SimpleNamespace(sequence=11),
        "witness_event": None, "project_watermark": None,
        "replay_model": (state, {}),
    }.items():
        mocks[name] = Mock(return_value=result)
        monkeypatch.setattr(budget, name, mocks[name])
    def original_proof(*args, proof=None, **kwargs):
        if proof is not None:
            proof.append(("current record", "canonical Event"))
        return b"checkpoint"
    mocks["verify_model_checkpoint"].side_effect = original_proof
    mocks["checkpoint_source"].side_effect = original_proof
    receipt = CoverageModelUsageReceipt(
        reservation=reservation(), input_tokens=1, output_tokens=2, total_tokens=3,
        checkpoint_ref="artifact://00000000-0000-0000-0000-000000000001",
        checkpoint_digest="c" * 64,
    )
    return SimpleNamespace(
        mode=mode, policy=policy, state=state, connection=connection, store=store,
        binding=binding, fence=object(), mocks=mocks, receipt=receipt,
    )


def reserve(env):
    return env.store.reserve_model_call(
        env.binding, env.receipt.reservation, fence=env.fence
    )


def test_unrelated_reservation_only_defers_historical_object_checks(env):
    result = reserve(env)
    assert result.invoke and result.event_watermark == 11
    assert env.mocks["verify_settled_checkpoints"].call_count == (env.mode == "eager")
    env.mocks["verify_model_checkpoint"].assert_not_called()
    env.mocks["preflight_original_volume"].assert_called_once()
    assert env.mocks["preflight_original_volume"].call_args.kwargs["_incremental_keys"] == (
        set() if env.mode == "final_certification" else None
    )
    env.mocks["validate_reservation"].assert_called_once()
    assert env.mocks["validate_write"].call_count == 2
    env.mocks["check_checkpoint_retention"].assert_called_once()
    env.mocks["lock_run"].assert_called_once_with(
        env.connection, "deployment", env.binding, env.fence
    )


@pytest.mark.parametrize("operation", ["retry", "settle", "settle_retry"])
@pytest.mark.parametrize("tampered", [False, True])
def test_current_receipt_always_requires_exact_checkpoint(env, operation, tampered):
    settled = operation != "settle"
    env.mocks["indexed_call"].return_value = {
        "reservation": env.receipt.reservation.model_dump(mode="json"),
        "receipt": env.receipt.model_dump(mode="json") if settled else None,
        "reserved_sequence": 7, "receipt_sequence": 8 if settled else None,
    }
    if tampered:
        env.mocks["verify_model_checkpoint"].side_effect = ValueError("tampered current proof")

    def act():
        return reserve(env) if operation == "retry" else env.store.record_model_usage(
            env.binding, env.receipt, fence=env.fence
        )

    if tampered:
        with pytest.raises(ValueError, match="tampered current proof"):
            act()
        env.mocks["append_coverage_event"].assert_not_called()
    else:
        result = act()
        if operation == "retry":
            assert not result.invoke and result.receipt == env.receipt
        else:
            assert result == (8 if settled else 11)
        env.mocks["check_checkpoint_retention"].assert_called_once()
    env.mocks["verify_model_checkpoint"].assert_called_once_with(
        env.connection, "deployment", env.binding, env.receipt, env.store._artifacts,
        reserved_sequence=7, receipt_sequence=8 if settled else None,
        retention_deadlines=[],
        **({"proof": [] if tampered else [("current record", "canonical Event")]}
           if operation != "retry" else {}),
    )
    env.mocks["preflight_original_volume"].assert_called_once()
    assert env.mocks["preflight_original_volume"].call_args.kwargs["_incremental_keys"] == (
        (set() if operation == "retry" else {env.receipt.reservation.key})
        if env.mode == "final_certification" else None
    )
    env.mocks["verify_settled_checkpoints"].assert_not_called()


@pytest.mark.parametrize(
    "guard", ["fence", "cancel", "calls", "tokens", "clock", "retention", "volume"]
)
def test_new_mode_keeps_reservation_guards(env, guard):
    if guard == "fence":
        env.mocks["lock_run"].side_effect = ValueError("fence")
    elif guard == "cancel":
        env.mocks["lock_run"].return_value = ({"cancelled": True}, 10)
    elif guard in {"calls", "tokens"}:
        env.mocks["indexed_state"].return_value = env.state.model_copy(update={
            "calls" if guard == "calls" else "charged_tokens":
                env.policy.max_calls if guard == "calls" else env.policy.max_tokens,
        })
    elif guard == "clock":
        env.mocks["validate_write"].return_value = (env.policy.deadline, "b" * 64, None)
    else:
        name = "check_checkpoint_retention" if guard == "retention" else "preflight_original_volume"
        env.mocks[name].side_effect = ValueError(guard)
    with pytest.raises((ValueError, CoverageRefusedError)):
        reserve(env)
    if guard != "retention":
        env.mocks["append_coverage_event"].assert_not_called()


def test_budget_state_uses_index_only_for_opted_in_policy_and_keeps_preflight(env):
    deadline = NOW + timedelta(seconds=30)

    def preflight(*args, retention_deadlines, _incremental_keys, _policy):
        assert _incremental_keys == set()
        assert _policy == env.policy
        retention_deadlines.append(deadline)

    env.mocks["preflight_original_volume"].side_effect = preflight
    assert env.store.model_budget_state(env.binding) == env.state
    deferred = env.mode == "final_certification"
    assert env.mocks["indexed_state"].call_count == deferred
    assert env.mocks["preflight_original_volume"].call_count == deferred
    assert env.mocks["replay_model"].call_count == (not deferred)
    env.mocks["check_checkpoint_retention"].assert_called_once_with(
        env.connection, [deadline] if deferred else []
    )
    env.mocks["lock_run"].assert_called_once_with(
        env.connection, "deployment", env.binding, None
    )


def test_legacy_reservation_still_refuses_corrupt_historical_proof(env):
    env.mocks["verify_settled_checkpoints"].side_effect = ValueError("historical proof")
    if env.mode == "eager":
        with pytest.raises(ValueError, match="historical proof"):
            reserve(env)
        env.mocks["append_coverage_event"].assert_not_called()
    else:
        assert reserve(env).invoke


def test_final_certification_always_uses_independent_replay(env, monkeypatch):
    replay = Mock(side_effect=ValueError("independent historical proof failed"))
    monkeypatch.setattr(source, "replay_model", replay)
    with pytest.raises(ValueError, match="independent historical proof failed"):
        source.certify_model_budget(
            env.connection, "deployment", env.binding, at=NOW, artifacts=env.store._artifacts
        )
    replay.assert_called_once_with(
        env.connection, "deployment", env.binding, artifacts=env.store._artifacts,
        retention_deadlines=[],
    )
    env.mocks["indexed_state"].assert_not_called()
