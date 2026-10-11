"""Explicit native incremental admission defers history, never current authority."""
# ruff: noqa: F811

from unittest.mock import Mock

import pytest
from agent_core.domain.coverage_contracts import CoverageRefusalReason as Reason
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_integrations.coverage_model_invocation import _utc_now

from tests.agent_integrations.test_coverage_model_invocation import compose, env  # noqa: F401


def incremental(env):
    env.policy = env.policy.model_copy(update={"validation_mode": "final_certification"})
    env.budget.policy = env.policy
    return compose(env)


def test_incremental_boundaries_do_not_reread_frozen_history(env, monkeypatch):
    invocation = incremental(env)
    read = Mock(side_effect=AssertionError("historical proof read"))
    authority = Mock()
    monkeypatch.setattr(invocation, "_required", read)
    monkeypatch.setattr(invocation, "check_authority", authority)
    assert invocation._boundary() == env.now
    assert invocation._boundary() == env.now
    assert authority.call_count == 4  # Injected clock callback keeps a post-callback guard.
    read.assert_not_called()


@pytest.mark.parametrize("failure", ["authority", "deadline", "retention"])
def test_incremental_boundaries_still_refuse_current_guards(env, failure):
    invocation = incremental(env)
    if failure == "authority":
        env.authority_error = Reason.CANCELLED
    elif failure == "deadline":
        env.now = env.policy.deadline
    else:
        invocation._retained_until = env.now
    with pytest.raises(CoverageRefusedError):
        invocation._boundary()


def test_eager_boundary_still_rechecks_historical_body(env, monkeypatch):
    invocation = compose(env)
    monkeypatch.setattr(invocation, "_required", Mock(return_value=b"corrupt"))
    with pytest.raises(CoverageRefusedError):
        invocation._boundary()


def test_caller_cannot_enable_incremental_mode_without_matching_native_admission(env):
    env.policy = env.policy.model_copy(update={"validation_mode": "final_certification"})
    with pytest.raises(CoverageRefusedError):
        compose(env)
    assert not env.requests


def test_incremental_fence_callback_revocation_is_checked_after_callback(env, monkeypatch):
    invocation = incremental(env)
    fresh = invocation.fresh_fence

    def revoke():
        fence = fresh()
        env.authority_error = Reason.CANCELLED
        return fence

    monkeypatch.setattr(invocation, "fresh_fence", revoke)
    with pytest.raises(CoverageRefusedError):
        invocation._fence()
    assert not env.requests


def test_native_clock_boundary_has_one_current_check(env, monkeypatch):
    invocation = incremental(env)
    authority = Mock()
    monkeypatch.setattr(invocation, "now", _utc_now)
    monkeypatch.setattr(invocation, "_time", Mock(return_value=env.now))
    monkeypatch.setattr(invocation, "check_authority", authority)
    assert invocation._boundary() == env.now
    assert invocation._boundary() == env.now
    assert authority.call_count == 2


def test_injected_clock_revocation_is_refused_before_boundary_returns(env, monkeypatch):
    invocation = incremental(env)

    def clock():
        env.authority_error = Reason.CANCELLED
        return env.now

    monkeypatch.setattr(invocation, "now", clock)
    with pytest.raises(CoverageRefusedError):
        invocation._boundary()
    assert not env.requests
