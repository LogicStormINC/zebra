from __future__ import annotations

from datetime import UTC, datetime

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.policies import PolicyDecisionType
from agent_core.domain.tools import ToolCall
from agent_security import LocalPolicyEngine, PolicyProfile


@pytest.mark.parametrize(
    "tool_name",
    [
        "finos.journals.list",
        "finos.journals.get",
        "finos.snapshots.list",
        "finos.snapshots.get",
        "finos.transactions.list",
        "finos.notes.list",
        "finos.notes.get",
        "finos.securities.resolve",
        "finos.trade_log_quality.validate",
    ],
)
def test_finos_business_tools_are_explicit_read_only_policy_allowances(tool_name: str) -> None:
    decision = LocalPolicyEngine(profile=PolicyProfile.READ_ONLY).evaluate_tool_call(
        ToolCall(
            tool_call_id=new_tool_call_id(),
            name=tool_name,
            arguments={},
            created_at=datetime.now(UTC),
        )
    )

    assert decision.decision is PolicyDecisionType.ALLOW


@pytest.mark.parametrize(
    "tool_name",
    [
        "finos.backtest.run",
        "finos.core.confirm",
        "finos.tradingview.read",
        "finos.trench.list",
    ],
)
def test_policy_does_not_treat_unlisted_finos_tools_as_read_only(tool_name: str) -> None:
    decision = LocalPolicyEngine(profile=PolicyProfile.READ_ONLY).evaluate_tool_call(
        ToolCall(
            tool_call_id=new_tool_call_id(),
            name=tool_name,
            arguments={},
            created_at=datetime.now(UTC),
        )
    )

    assert decision.decision is PolicyDecisionType.DENY


@pytest.mark.parametrize("profile", list(PolicyProfile))
def test_account_change_proposal_is_denied_without_a_v2_task_provider(
    profile: PolicyProfile,
) -> None:
    decision = LocalPolicyEngine(profile=profile).evaluate_tool_call(
        ToolCall(
            tool_call_id=new_tool_call_id(),
            name="finos.account_changes.propose",
            arguments={},
            created_at=datetime.now(UTC),
        )
    )

    assert decision.decision is PolicyDecisionType.DENY


def test_account_change_proposal_requires_the_explicit_v2_task_provider_gate() -> None:
    decision = LocalPolicyEngine(
        profile=PolicyProfile.READ_ONLY,
        allow_finos_account_changes_proposal=True,
    ).evaluate_tool_call(
        ToolCall(
            tool_call_id=new_tool_call_id(),
            name="finos.account_changes.propose",
            arguments={},
            created_at=datetime.now(UTC),
        )
    )

    assert decision.decision is PolicyDecisionType.ALLOW
