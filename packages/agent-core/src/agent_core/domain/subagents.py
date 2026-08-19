"""Subagent domain contracts: legacy research shapes plus the v2 surface.

SUBAGENT-CONTRACT-V2-01 (plan section 7): roles, execution requests,
evidence refs, usage receipts, completion-gate receipts and result bundles
are model-agnostic, Host-agnostic and secret-free with deterministic
digests. The legacy research dataclasses stay for the local fast path.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_core.domain.identifiers import SubagentId, TaskId

MAX_TEXT_LENGTH = 512
MAX_EVIDENCE_REFS = 64


class SubagentStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class DelegationMode(StrEnum):
    """Who decides delegation, and whether it is mandatory (P0.1 fix)."""

    DISABLED = "disabled"
    AUTO = "auto"
    REQUIRED_ONCE = "required_once"
    ORCHESTRATED = "orchestrated"


class SubagentRole(StrEnum):
    RESEARCHER = "researcher"
    EXPLORER = "explorer"
    PLANNER = "planner"
    IMPLEMENTER = "implementer"
    TESTER = "tester"
    REVIEWER = "reviewer"
    SYNTHESIZER = "synthesizer"


READ_ONLY_ROLES = frozenset(
    {
        SubagentRole.RESEARCHER,
        SubagentRole.EXPLORER,
        SubagentRole.PLANNER,
        SubagentRole.REVIEWER,
        SubagentRole.SYNTHESIZER,
    }
)


class EvidenceRef(BaseModel):
    """One verifiable piece of child-collected evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    uri: str = Field(min_length=1, max_length=2048)
    kind: str = Field(min_length=1, max_length=128)
    tool_name: str = Field(min_length=1, max_length=128)
    digest: str | None = Field(default=None, min_length=16, max_length=128)
    observed_at: datetime

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.observed_at.tzinfo is None:
            raise ValueError("evidence observed_at must be timezone-aware")
        return self

    @property
    def evidence_digest(self) -> str:
        canonical = {
            "evidenceId": self.evidence_id,
            "uri": self.uri,
            "kind": self.kind,
            "toolName": self.tool_name,
            "digest": self.digest,
        }
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class UsageReceipt(BaseModel):
    """Bounded accounting of one child run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    model_tokens: int = Field(ge=0, default=0)
    runtime_seconds: int = Field(ge=0, default=0)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.model_calls == 0 and self.tool_calls == 0:
            raise ValueError("usage receipt must record at least one call")
        return self


class CompletionGateReceipt(BaseModel):
    """Deterministic gate verdict — the model's claim is only a signal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_name: str = Field(min_length=1, max_length=128)
    passed: bool
    reason_code: str = Field(min_length=1, max_length=128)
    detail: str | None = Field(default=None, max_length=MAX_TEXT_LENGTH)
    evaluated_at: datetime

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.evaluated_at.tzinfo is None:
            raise ValueError("gate receipt evaluated_at must be timezone-aware")
        if self.passed and self.reason_code == "no_evidence_collected":
            raise ValueError("a passed gate cannot cite missing evidence")
        return self


class SubagentResultBundle(BaseModel):
    """The stable child result the parent and gates consume (plan 7.4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    child_task_id: TaskId | None = None
    subagent_id: str = Field(min_length=1, max_length=128)
    status: Literal["completed", "failed", "cancelled", "timed_out"]
    summary: str = Field(min_length=1, max_length=8192)
    evidence: tuple[EvidenceRef, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    usage: UsageReceipt | None = None
    gate_receipts: tuple[CompletionGateReceipt, ...] = ()

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if len(self.evidence) > MAX_EVIDENCE_REFS:
            raise ValueError("result bundle exceeds the evidence bound")
        if self.status == "completed":
            if self.usage is None:
                raise ValueError("completed bundles must carry a usage receipt")
            if not any(receipt.passed for receipt in self.gate_receipts):
                raise ValueError("completed bundles require at least one passed gate")
        return self

    @property
    def result_digest(self) -> str:
        canonical = {
            "subagentId": self.subagent_id,
            "status": self.status,
            "summary": self.summary,
            "evidence": [ref.evidence_digest for ref in self.evidence],
            "artifactRefs": list(self.artifact_refs),
            "gateReceipts": [
                {
                    "gate": receipt.gate_name,
                    "passed": receipt.passed,
                    "reason": receipt.reason_code,
                }
                for receipt in self.gate_receipts
            ],
        }
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def research_evidence_gate(
    evidence_count: int,
    successful_tool_calls: int,
    *,
    evaluated_at: datetime | None = None,
) -> CompletionGateReceipt:
    """The P0.4 fix: zero-evidence research can never complete."""

    passed = evidence_count >= 1 and successful_tool_calls >= 1
    return CompletionGateReceipt(
        gate_name="research.evidence",
        passed=passed,
        reason_code="evidence_satisfied" if passed else "no_evidence_collected",
        detail=(
            f"evidence={evidence_count} successful_tool_calls={successful_tool_calls}"
        ),
        evaluated_at=evaluated_at or datetime.now(UTC),
    )


# --- Legacy local fast-path shapes (retained until SUBAGENT-CLOUD-CUTOVER-01) ---


@dataclass(frozen=True)
class ResearchSource:
    reference: str
    kind: str

    def __post_init__(self) -> None:
        if not self.reference.strip() or not self.kind.strip():
            raise ValueError("research source fields must not be blank")


@dataclass(frozen=True)
class ResearchSubagentTask:
    objective: str
    workspace_root: Path
    max_model_calls: int = 3
    max_tool_calls: int = 2
    depth: int = 1

    def __post_init__(self) -> None:
        if not self.objective.strip():
            raise ValueError("research objective must not be blank")
        if not self.workspace_root.is_absolute():
            raise ValueError("research workspace_root must be absolute")
        if self.max_model_calls <= 0 or self.max_tool_calls <= 0:
            raise ValueError("research budgets must be positive")
        if self.depth <= 0:
            raise ValueError("research depth must be positive")


@dataclass(frozen=True)
class ResearchSubagentResult:
    subagent_id: SubagentId
    status: SubagentStatus
    summary: str
    sources: tuple[ResearchSource, ...] = ()
    confidence: float = 0.0
    model_calls_used: int = 0
    tool_calls_used: int = 0
    provenance: str = "local_read_only_research"

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("research result summary must not be blank")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("research confidence must be between zero and one")
        if self.model_calls_used < 0 or self.tool_calls_used < 0:
            raise ValueError("research usage cannot be negative")
        if not self.provenance.strip():
            raise ValueError("research provenance must not be blank")
