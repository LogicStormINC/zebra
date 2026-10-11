"""Fresh receipt-backed initialization; never downgrade corrupt proofs."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agent_storage.postgres import coverage_model_budget as budget

from tests.agent_storage.test_coverage_model_validation_mode import env  # noqa: F401


def qualified(scenario):
    scenario.store._execution_receipts = True
    scenario.store._execution_receipt_verifier = "native"
    scenario.store._artifacts = SimpleNamespace(
        _execution_receipt_verifier=Mock(return_value="native"), check_authority=Mock(),
    )
    return SimpleNamespace(budget=scenario.state, verifier_contract="native",
                           valid_until=scenario.policy.deadline)


def test_default_initialization_does_not_query_receipts(env, monkeypatch):  # noqa: F811
    read = Mock(side_effect=AssertionError("default receipt read"))
    monkeypatch.setattr(budget, "read_execution_receipt", read)
    assert env.store.initialize_model_budget(env.binding, fence=env.fence) == env.policy
    read.assert_not_called()
    env.mocks["replay_model"].assert_called_once()


@pytest.mark.parametrize("env", ["final_certification"], indirect=True)
def test_qualified_initialization_reuses_only_fresh_exact_policy(env, monkeypatch):  # noqa: F811
    facts = qualified(env)
    read = Mock(return_value=facts)
    monkeypatch.setattr(budget, "read_execution_receipt", read)
    assert env.store.initialize_model_budget(env.binding, fence=env.fence) == env.policy
    read.assert_called_once_with(env.connection, "deployment", env.binding, _unchanged_model=True)
    env.mocks["replay_model"].assert_not_called()
    assert env.store._artifacts.check_authority.call_count == 2
    assert env.mocks["validate_write"].call_count == 2
    assert env.mocks["check_checkpoint_retention"].call_count == 2


@pytest.mark.parametrize("failure", ["missing", "verifier", "policy", "corruption", "revocation"])
def test_receipt_fallback_is_distinct_from_refusal(env, monkeypatch, failure):  # noqa: F811
    facts = qualified(env)
    read = Mock(return_value=facts)
    monkeypatch.setattr(budget, "read_execution_receipt", read)
    if failure == "missing":
        read.return_value = None  # Includes new native MODEL tail / legacy reader result.
        summary = Mock(return_value=None)
        monkeypatch.setattr(budget, "summary_state", summary)
    elif failure == "verifier":
        facts.verifier_contract = "other"
    elif failure == "policy":
        env.mocks["task_policy"].return_value = None
    elif failure == "corruption":
        read.side_effect = ValueError("corrupt native source")
    else:
        env.store._artifacts.check_authority.side_effect = [None, ValueError("revoked")]
    if failure in {"missing", "verifier"}:
        assert env.store.initialize_model_budget(env.binding, fence=env.fence) == env.policy
        env.mocks["replay_model"].assert_called_once()
        if failure == "missing" and env.mode == "final_certification":
            summary.assert_called_once_with(
                env.connection, "deployment", env.binding, env.policy,
            )
    else:
        with pytest.raises(ValueError):
            env.store.initialize_model_budget(env.binding, fence=env.fence)
        env.mocks["replay_model"].assert_not_called()
