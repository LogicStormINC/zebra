from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class PolicyDecisionType(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class PolicyDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision: PolicyDecisionType
    reason: str
    policy_profile: str
