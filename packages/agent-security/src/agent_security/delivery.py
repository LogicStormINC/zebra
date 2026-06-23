from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from agent_security.policy import PolicyProfile


class DeliveryDecisionType(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True)
class DeliveryDecision:
    decision: DeliveryDecisionType
    reason: str
    policy_profile: str


class CommitPolicy:
    def evaluate(self, policy_profile: str | None) -> DeliveryDecision:
        if policy_profile != PolicyProfile.FULL_ACCESS.value:
            return DeliveryDecision(
                decision=DeliveryDecisionType.DENY,
                reason="commit requires full_access session policy",
                policy_profile=policy_profile or PolicyProfile.WORKSPACE_WRITE.value,
            )
        return DeliveryDecision(
            decision=DeliveryDecisionType.ALLOW,
            reason="commit is allowed by full_access session policy",
            policy_profile=PolicyProfile.FULL_ACCESS.value,
        )
