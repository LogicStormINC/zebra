"""Five-layer completion gate (ORCH-COMPLETION-GATE-01, plan section 11).

Completion authority belongs to the Control Plane. The model's claim is
one candidate input; every layer must pass (or explicitly block on human
approval) before a node may complete. Fail-closed at the first failing
layer, with one receipt per evaluated layer for audit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_core.domain.subagents import CompletionGateReceipt

MAX_NOTE = 512


class ToolchainResult(BaseModel):
    """One Layer-2 verification outcome (tests/lint/typecheck/build/diff)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    check_name: str = Field(min_length=1, max_length=128)
    passed: bool


class ReviewerVerdict(BaseModel):
    """Layer-4 input only — never the decision itself."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: str = Field(pattern="^(pass|fail|needs_human)$")
    findings_count: int = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)


class HumanApproval(BaseModel):
    """Layer-5 signal recorded by the approval surface."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    approved: bool
    approver_subject: str = Field(min_length=1, max_length=128)


class GateInput(BaseModel):
    """Durable facts the gate evaluates — no model free-text trust."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_claimed_complete: bool = False
    required_artifacts: tuple[str, ...] = ()
    present_artifacts: tuple[str, ...] = ()
    evidence_count: int = Field(ge=0, default=0)
    successful_tool_calls: int = Field(ge=0, default=0)
    toolchain_results: tuple[ToolchainResult, ...] = ()
    toolchain_required: bool = False
    binding_digest: str = Field(min_length=64, max_length=64)
    expected_binding_digest: str = Field(min_length=64, max_length=64)
    grant_expired: bool = False
    namespace_match: bool = True
    capabilities_expanded: bool = False
    uncertain_effects: int = Field(ge=0, default=0)
    reviewer_verdict: ReviewerVerdict | None = None
    reviewer_required: bool = False
    human_approval_required: bool = False
    human_approval: HumanApproval | None = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.human_approval_required and self.human_approval is not None:
            if not self.human_approval.approved and self.model_claimed_complete:
                pass  # rejection handled by the gate, not validation
        return self


@dataclass(frozen=True)
class GateEvaluation:
    """Control-plane decision: pass, fail, or block on human approval."""

    receipts: tuple[CompletionGateReceipt, ...]
    passed: bool
    blocked: bool
    reason_code: str

    @property
    def deciding_receipt(self) -> CompletionGateReceipt | None:
        return self.receipts[-1] if self.receipts else None


def _receipt(
    layer: str,
    passed: bool,
    reason: str,
    detail: str,
) -> CompletionGateReceipt:
    return CompletionGateReceipt(
        gate_name=layer,
        passed=passed,
        reason_code=reason,
        detail=detail[:MAX_NOTE],
        evaluated_at=datetime.now(UTC),
    )


def evaluate_gate(subject: str, candidate: GateInput) -> GateEvaluation:
    """Evaluate layers 1→5 deterministically; first failure decides."""

    receipts: list[CompletionGateReceipt] = []

    if not candidate.model_claimed_complete:
        receipts.append(
            _receipt(
                f"{subject}.model_claim",
                False,
                "model_did_not_claim_completion",
                "the gate only evaluates completion claims",
            )
        )
        return GateEvaluation(tuple(receipts), False, False, "model_did_not_claim_completion")

    # Layer 1: domain predicates
    missing = [
        artifact
        for artifact in candidate.required_artifacts
        if artifact not in candidate.present_artifacts
    ]
    if missing:
        receipts.append(
            _receipt(
                f"{subject}.domain",
                False,
                "required_artifact_missing",
                ",".join(missing),
            )
        )
        return GateEvaluation(tuple(receipts), False, False, "required_artifact_missing")
    if candidate.evidence_count < 1 or candidate.successful_tool_calls < 1:
        receipts.append(
            _receipt(
                f"{subject}.domain",
                False,
                "no_evidence_collected",
                f"evidence={candidate.evidence_count} tools={candidate.successful_tool_calls}",
            )
        )
        return GateEvaluation(tuple(receipts), False, False, "no_evidence_collected")
    receipts.append(_receipt(f"{subject}.domain", True, "domain_predicates_satisfied", ""))

    # Layer 2: toolchain verification
    if candidate.toolchain_required or candidate.toolchain_results:
        failed = [item.check_name for item in candidate.toolchain_results if not item.passed]
        if failed:
            receipts.append(
                _receipt(
                    f"{subject}.toolchain",
                    False,
                    "toolchain_check_failed",
                    ",".join(failed),
                )
            )
            return GateEvaluation(tuple(receipts), False, False, "toolchain_check_failed")
        if candidate.toolchain_required and not candidate.toolchain_results:
            receipts.append(
                _receipt(
                    f"{subject}.toolchain",
                    False,
                    "toolchain_evidence_missing",
                    "toolchain required but no results supplied",
                )
            )
            return GateEvaluation(
                tuple(receipts), False, False, "toolchain_evidence_missing"
            )
    receipts.append(_receipt(f"{subject}.toolchain", True, "toolchain_satisfied", ""))

    # Layer 3: policy and authority
    if candidate.binding_digest != candidate.expected_binding_digest:
        receipts.append(
            _receipt(
                f"{subject}.policy",
                False,
                "binding_digest_drifted",
                "child binding no longer matches the frozen plan",
            )
        )
        return GateEvaluation(tuple(receipts), False, False, "binding_digest_drifted")
    if candidate.grant_expired:
        receipts.append(
            _receipt(f"{subject}.policy", False, "grant_expired", "host grant expired")
        )
        return GateEvaluation(tuple(receipts), False, False, "grant_expired")
    if not candidate.namespace_match:
        receipts.append(
            _receipt(f"{subject}.policy", False, "namespace_mismatch", "")
        )
        return GateEvaluation(tuple(receipts), False, False, "namespace_mismatch")
    if candidate.capabilities_expanded:
        receipts.append(
            _receipt(
                f"{subject}.policy",
                False,
                "capabilities_expanded",
                "the attempt exceeded its frozen capability set",
            )
        )
        return GateEvaluation(tuple(receipts), False, False, "capabilities_expanded")
    if candidate.uncertain_effects:
        receipts.append(
            _receipt(
                f"{subject}.policy",
                False,
                "uncertain_effects_pending",
                f"count={candidate.uncertain_effects}",
            )
        )
        return GateEvaluation(tuple(receipts), False, False, "uncertain_effects_pending")
    receipts.append(_receipt(f"{subject}.policy", True, "policy_satisfied", ""))

    # Layer 4: reviewer verdict (input only)
    if candidate.reviewer_verdict is not None:
        verdict = candidate.reviewer_verdict
        if verdict.decision == "fail":
            receipts.append(
                _receipt(
                    f"{subject}.reviewer",
                    False,
                    "reviewer_rejected",
                    f"findings={verdict.findings_count}",
                )
            )
            return GateEvaluation(tuple(receipts), False, False, "reviewer_rejected")
        if verdict.decision == "needs_human":
            receipts.append(
                _receipt(
                    f"{subject}.reviewer",
                    False,
                    "reviewer_requests_human",
                    "escalating to human approval",
                )
            )
            # fall through to Layer 5 with approval now required
            approval_required = True
        else:
            receipts.append(
                _receipt(f"{subject}.reviewer", True, "reviewer_passed", "")
            )
            approval_required = candidate.human_approval_required
    else:
        approval_required = candidate.human_approval_required
        if candidate.reviewer_required:
            receipts.append(
                _receipt(
                    f"{subject}.reviewer",
                    False,
                    "reviewer_verdict_missing",
                    "a reviewer verdict is required for this node",
                )
            )
            return GateEvaluation(tuple(receipts), False, False, "reviewer_verdict_missing")

    # Layer 5: human approval
    if approval_required:
        approval = candidate.human_approval
        if approval is None:
            receipts.append(
                _receipt(
                    f"{subject}.human",
                    False,
                    "human_approval_required",
                    "gate blocks until approval is recorded",
                )
            )
            return GateEvaluation(tuple(receipts), False, True, "human_approval_required")
        if not approval.approved:
            receipts.append(
                _receipt(
                    f"{subject}.human",
                    False,
                    "human_rejected",
                    f"approver={approval.approver_subject}",
                )
            )
            return GateEvaluation(tuple(receipts), False, False, "human_rejected")
        receipts.append(
            _receipt(
                f"{subject}.human",
                True,
                "human_approved",
                f"approver={approval.approver_subject}",
            )
        )

    receipts.append(
        _receipt(f"{subject}.completion", True, "all_layers_passed", "")
    )
    return GateEvaluation(tuple(receipts), True, False, "all_layers_passed")
