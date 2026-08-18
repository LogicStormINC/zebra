"""EXT-HOOK-01: declarative hook contract tests."""

from __future__ import annotations

import pytest
from agent_core.harness.hooks import (
    HookDecision,
    HookDefinition,
    HookFailureMode,
    HookOutcome,
    order_hooks,
    resolve_pre_tool_decision,
)

DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64


def _hook(**overrides: object) -> HookDefinition:
    payload: dict[str, object] = {
        "name": "guard-writes",
        "kind": "pre_tool_use",
        "package_digest": DIGEST,
        "tool_matchers": ("files.write", "command.*"),
    }
    payload.update(overrides)
    return HookDefinition.model_validate(payload)


def test_hook_definition_binds_digest_and_failure_mode() -> None:
    hook = _hook()
    assert hook.failure_mode is HookFailureMode.FAIL_CLOSED
    audit = _hook(kind="post_tool_use", tool_matchers=())
    assert audit.failure_mode is HookFailureMode.FAIL_OPEN
    assert audit.matches_tool("files.write") is False


def test_hook_definition_rejects_invalid_shapes() -> None:
    with pytest.raises(ValueError):
        _hook(name="Bad Name")
    with pytest.raises(ValueError):
        _hook(package_digest="sha256:short")
    with pytest.raises(ValueError):
        _hook(tool_matchers=())  # pre_tool_use requires matchers
    with pytest.raises(ValueError):
        _hook(kind="stop")  # non-pre hooks reject matchers
    with pytest.raises(ValueError):
        _hook(timeout_ms=0)


def test_pre_tool_matching_includes_wildcards() -> None:
    hook = _hook()
    assert hook.matches_tool("files.write") is True
    assert hook.matches_tool("command.run") is True
    assert hook.matches_tool("files.read") is False


def test_order_hooks_is_stable_and_deterministic() -> None:
    first = _hook(order=0, package_digest=DIGEST)
    second = _hook(name="zeta-guard", order=0, package_digest=OTHER_DIGEST)
    third = _hook(name="alpha-guard", order=5)
    ordered = order_hooks((third, second, first))
    assert [hook.name for hook in ordered] == ["guard-writes", "zeta-guard", "alpha-guard"]
    assert order_hooks((third, second, first)) == ordered


def test_outcome_requires_reason_for_non_allow() -> None:
    HookOutcome(hook_name="guard-writes", decision=HookDecision.ALLOW)
    with pytest.raises(ValueError):
        HookOutcome(hook_name="guard-writes", decision=HookDecision.DENY)
    with pytest.raises(ValueError):
        HookOutcome(
            hook_name="guard-writes",
            decision=HookDecision.ALLOW,
            failed=True,
        )


def test_decision_resolution_orders_deny_first() -> None:
    allow = HookOutcome(hook_name="a", decision=HookDecision.ALLOW)
    approval = HookOutcome(
        hook_name="b", decision=HookDecision.REQUIRE_APPROVAL, reason="policy"
    )
    deny = HookOutcome(hook_name="c", decision=HookDecision.DENY, reason="blocked")
    assert resolve_pre_tool_decision((allow,)) is HookDecision.ALLOW
    assert (
        resolve_pre_tool_decision((allow, approval)) is HookDecision.REQUIRE_APPROVAL
    )
    assert resolve_pre_tool_decision((allow, approval, deny)) is HookDecision.DENY
    assert resolve_pre_tool_decision(()) is HookDecision.ALLOW
