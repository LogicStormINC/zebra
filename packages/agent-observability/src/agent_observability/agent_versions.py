"""Deterministic Agent Version publication gate (AGENT-DEF-EVAL-01).

Aggregates deterministic Eval/replay evidence for one immutable Definition
Version and produces an auditable gate decision. LLM-as-judge is supplemental
and can never replace deterministic/security conditions. This module never
mutates Release state.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from agent_core.domain.identifiers import (
    AgentDefinitionId,
    AgentDefinitionVersionId,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator

REQUIRED_PUBLICATION_CONDITIONS = (
    "regression",
    "safety",
    "recovery",
    "cost",
    "latency",
)


class AgentVersionPublicationGateStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class AgentVersionPublicationCondition(BaseModel):
    """One deterministic condition with an explicit reason and evidence pin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    passed: bool
    reason: str = Field(min_length=1, max_length=512)
    evidence_ref: str | None = Field(default=None, max_length=512)

    @field_validator("name", "reason")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("condition name and reason must not be blank")
        return stripped


class AgentVersionPublicationGate(BaseModel):
    """Auditable publication decision for one exact Version digest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    definition_id: AgentDefinitionId
    version_id: AgentDefinitionVersionId
    definition_digest: str
    policy_version: str = Field(min_length=1, max_length=64)
    status: AgentVersionPublicationGateStatus
    conditions: tuple[AgentVersionPublicationCondition, ...] = Field(min_length=1)
    required_condition_names: tuple[str, ...]
    llm_judge_supplemental: bool = False
    evaluator_actor: str = Field(min_length=1, max_length=2_048)
    evaluated_at: datetime

    @field_validator("definition_digest")
    @classmethod
    def require_sha256(cls, value: str) -> str:
        stripped = value.strip().lower()
        if len(stripped) != 64 or any(
            character not in "0123456789abcdef" for character in stripped
        ):
            raise ValueError("definition_digest must be a lowercase sha256 string")
        return stripped

    @field_validator("evaluator_actor", "policy_version")
    @classmethod
    def require_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("gate text fields must not be blank")
        return stripped

    @field_validator("evaluated_at")
    @classmethod
    def require_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("evaluated_at must be timezone-aware")
        return value

    @property
    def passed(self) -> bool:
        return self.status is AgentVersionPublicationGateStatus.PASSED


class AgentVersionPublicationGateService:
    """Deterministic gate evaluation; evidence must pin exact Version identity."""

    def evaluate(
        self,
        *,
        definition_id: AgentDefinitionId,
        version_id: AgentDefinitionVersionId,
        definition_digest: str,
        policy_version: str,
        conditions: tuple[AgentVersionPublicationCondition, ...],
        required_condition_names: tuple[str, ...] = REQUIRED_PUBLICATION_CONDITIONS,
        llm_judge_supplemental: bool = False,
        evaluator_actor: str,
        evaluated_at: datetime,
    ) -> AgentVersionPublicationGate:
        by_name = {condition.name: condition for condition in conditions}
        missing = tuple(
            name for name in required_condition_names if name not in by_name
        )
        if missing:
            return AgentVersionPublicationGate(
                definition_id=definition_id,
                version_id=version_id,
                definition_digest=definition_digest,
                policy_version=policy_version,
                status=AgentVersionPublicationGateStatus.PENDING,
                conditions=conditions,
                required_condition_names=required_condition_names,
                llm_judge_supplemental=llm_judge_supplemental,
                evaluator_actor=evaluator_actor,
                evaluated_at=evaluated_at,
            )
        failed = tuple(
            condition
            for name in required_condition_names
            if not (condition := by_name[name]).passed
        )
        status = (
            AgentVersionPublicationGateStatus.FAILED
            if failed
            else AgentVersionPublicationGateStatus.PASSED
        )
        return AgentVersionPublicationGate(
            definition_id=definition_id,
            version_id=version_id,
            definition_digest=definition_digest,
            policy_version=policy_version,
            status=status,
            conditions=conditions,
            required_condition_names=required_condition_names,
            llm_judge_supplemental=llm_judge_supplemental,
            evaluator_actor=evaluator_actor,
            evaluated_at=evaluated_at,
        )
