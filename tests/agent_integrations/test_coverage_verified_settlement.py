"""Optional atomic settlement delivery; legacy/eager and callback guards remain."""
# ruff: noqa: F811

from unittest.mock import Mock

import pytest
from agent_core.domain.coverage_contracts import CoverageRefusalReason as Reason
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_core.domain.coverage_model_checkpoint import MODEL_CHECKPOINT_KIND

from tests.agent_integrations.test_coverage_model_invocation import (
    compose,
    env,  # noqa: F401
    invoke,
)


def native_settlement(env, monkeypatch):
    def settle(binding, receipt, *, fence):
        sequence = env.budget.record_model_usage(binding, receipt, fence=fence)
        body = env.payloads.bodies[next(
            key for key, row in env.payloads.rows.items() if row.kind == MODEL_CHECKPOINT_KIND
        )]
        return sequence, body

    monkeypatch.setattr(env.budget, "settle_model_checkpoint", Mock(side_effect=settle),
                        raising=False)
    return env.budget.settle_model_checkpoint


def incremental(env):
    env.policy = env.policy.model_copy(update={"validation_mode": "final_certification"})
    env.budget.policy = env.policy
    return compose(env)


def test_atomic_settlement_keeps_post_callback_original_reread(env, monkeypatch):
    settle = native_settlement(env, monkeypatch)
    invocation = incremental(env)
    required = Mock(wraps=invocation._required)
    monkeypatch.setattr(invocation, "_required", required)
    first = invoke(env, invocation)
    assert settle.call_count == 1
    assert sum(call.args[1] == MODEL_CHECKPOINT_KIND for call in required.call_args_list) == 2
    required.reset_mock()
    assert invoke(env, invocation) == first
    assert settle.call_count == 1
    assert sum(call.args[1] == MODEL_CHECKPOINT_KIND for call in required.call_args_list) == 1
    assert len(env.requests) == 1 and len(env.budget.receipts) == 1


@pytest.mark.parametrize("result", [(True, b""), (0, b""), (1, b"corrupt"),
                                    (1, bytearray()), (None, b"")])
def test_unusable_settlement_result_cannot_deliver_response(env, monkeypatch, result):
    monkeypatch.setattr(env.budget, "settle_model_checkpoint", Mock(return_value=result),
                        raising=False)
    with pytest.raises(CoverageRefusedError):
        invoke(env, incremental(env))
    assert not env.budget.receipts


def test_settlement_callback_revocation_refuses_delivery_without_erasing_charge(env, monkeypatch):
    settle = native_settlement(env, monkeypatch)
    original = settle.side_effect

    def revoke(*args, **kwargs):
        result = original(*args, **kwargs)
        env.authority_error = Reason.CANCELLED
        return result

    settle.side_effect = revoke
    with pytest.raises(CoverageRefusedError):
        invoke(env, incremental(env))
    assert len(env.requests) == 1 and len(env.budget.receipts) == 1


def test_post_settlement_physical_change_cannot_use_previously_verified_bytes(env, monkeypatch):
    settle = native_settlement(env, monkeypatch)
    original = settle.side_effect

    def corrupt(*args, **kwargs):
        result = original(*args, **kwargs)
        identifier = next(key for key, row in env.payloads.rows.items()
                          if row.kind == MODEL_CHECKPOINT_KIND)
        env.payloads.bodies[identifier] = b"corrupt"
        return result

    settle.side_effect = corrupt
    with pytest.raises(CoverageRefusedError, match="artifact_unavailable"):
        invoke(env, incremental(env))
    assert len(env.requests) == 1 and len(env.budget.receipts) == 1


def test_eager_does_not_use_optional_delivery_shortcut(env, monkeypatch):
    settle = native_settlement(env, monkeypatch)
    settle.side_effect = AssertionError("eager shortcut")
    invoke(env, compose(env))
    settle.assert_not_called()
    assert len(env.budget.receipts) == 1


def test_legacy_incremental_keeps_current_original_reread(env, monkeypatch):
    invocation = incremental(env)
    required = Mock(wraps=invocation._required)
    monkeypatch.setattr(invocation, "_required", required)
    invoke(env, invocation)
    assert sum(call.args[1] == MODEL_CHECKPOINT_KIND for call in required.call_args_list) == 2
