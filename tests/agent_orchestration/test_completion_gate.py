"""Completion gate tests: every layer's rejection branch plus the pass."""

from __future__ import annotations

from agent_orchestration.application.completion_gate import (
    GateInput,
    HumanApproval,
    ReviewerVerdict,
    ToolchainResult,
    evaluate_gate,
)

DIGEST = "a" * 64


def _input(**overrides: object) -> GateInput:
    payload: dict[str, object] = {
        "model_claimed_complete": True,
        "required_artifacts": ("artifact://report",),
        "present_artifacts": ("artifact://report",),
        "evidence_count": 2,
        "successful_tool_calls": 3,
        "binding_digest": DIGEST,
        "expected_binding_digest": DIGEST,
    }
    payload.update(overrides)
    return GateInput(**payload)  # type: ignore[arg-type]


class TestModelClaim:
    def test_gate_never_passes_without_a_model_claim(self) -> None:
        result = evaluate_gate("node", _input(model_claimed_complete=False))
        assert not result.passed
        assert result.reason_code == "model_did_not_claim_completion"


class TestLayerOne:
    def test_missing_required_artifact_fails(self) -> None:
        result = evaluate_gate("node", _input(present_artifacts=()))
        assert not result.passed
        assert result.reason_code == "required_artifact_missing"

    def test_zero_evidence_fails(self) -> None:
        result = evaluate_gate("node", _input(evidence_count=0))
        assert result.reason_code == "no_evidence_collected"

    def test_zero_successful_tools_fails(self) -> None:
        result = evaluate_gate("node", _input(successful_tool_calls=0))
        assert result.reason_code == "no_evidence_collected"


class TestLayerTwo:
    def test_failed_toolchain_check_fails(self) -> None:
        result = evaluate_gate(
            "node",
            _input(
                toolchain_results=(ToolchainResult(check_name="pytest", passed=False),)
            ),
        )
        assert result.reason_code == "toolchain_check_failed"

    def test_required_toolchain_without_results_fails(self) -> None:
        result = evaluate_gate("node", _input(toolchain_required=True))
        assert result.reason_code == "toolchain_evidence_missing"


class TestLayerThree:
    def test_binding_digest_drift_fails(self) -> None:
        result = evaluate_gate("node", _input(binding_digest="b" * 64))
        assert result.reason_code == "binding_digest_drifted"

    def test_expired_grant_fails(self) -> None:
        result = evaluate_gate("node", _input(grant_expired=True))
        assert result.reason_code == "grant_expired"

    def test_namespace_mismatch_fails(self) -> None:
        result = evaluate_gate("node", _input(namespace_match=False))
        assert result.reason_code == "namespace_mismatch"

    def test_capability_expansion_fails(self) -> None:
        result = evaluate_gate("node", _input(capabilities_expanded=True))
        assert result.reason_code == "capabilities_expanded"

    def test_uncertain_effects_block_completion(self) -> None:
        result = evaluate_gate("node", _input(uncertain_effects=1))
        assert result.reason_code == "uncertain_effects_pending"


class TestLayerFour:
    def test_reviewer_fail_fails_the_gate(self) -> None:
        result = evaluate_gate(
            "node",
            _input(
                reviewer_verdict=ReviewerVerdict(
                    decision="fail", findings_count=2, confidence=0.8
                )
            ),
        )
        assert result.reason_code == "reviewer_rejected"

    def test_reviewer_missing_when_required_fails(self) -> None:
        result = evaluate_gate("node", _input(reviewer_required=True))
        assert result.reason_code == "reviewer_verdict_missing"

    def test_reviewer_needs_human_blocks_pending_approval(self) -> None:
        result = evaluate_gate(
            "node",
            _input(
                reviewer_verdict=ReviewerVerdict(
                    decision="needs_human", findings_count=1, confidence=0.5
                )
            ),
        )
        assert not result.passed
        assert result.blocked is True
        assert result.reason_code == "human_approval_required"


class TestLayerFive:
    def test_required_approval_missing_blocks(self) -> None:
        result = evaluate_gate("node", _input(human_approval_required=True))
        assert result.blocked is True
        assert result.reason_code == "human_approval_required"

    def test_human_rejection_fails(self) -> None:
        result = evaluate_gate(
            "node",
            _input(
                human_approval_required=True,
                human_approval=HumanApproval(
                    approved=False, approver_subject="operator-1"
                ),
            ),
        )
        assert result.reason_code == "human_rejected"

    def test_approval_completes_the_gate(self) -> None:
        result = evaluate_gate(
            "node",
            _input(
                human_approval_required=True,
                human_approval=HumanApproval(
                    approved=True, approver_subject="operator-1"
                ),
            ),
        )
        assert result.passed
        assert result.reason_code == "all_layers_passed"


class TestHappyPath:
    def test_all_layers_pass(self) -> None:
        result = evaluate_gate(
            "node",
            _input(
                toolchain_results=(
                    ToolchainResult(check_name="pytest", passed=True),
                ),
                reviewer_verdict=ReviewerVerdict(
                    decision="pass", findings_count=0, confidence=0.9
                ),
            ),
        )
        assert result.passed
        assert result.blocked is False
        assert result.deciding_receipt is not None
        assert result.deciding_receipt.gate_name == "node.completion"
        layers = [receipt.gate_name for receipt in result.receipts]
        assert "node.domain" in layers and "node.policy" in layers
