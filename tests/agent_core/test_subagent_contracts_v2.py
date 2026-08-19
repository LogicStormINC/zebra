"""Subagent v2 contracts: modes, bundles, gates, evidence semantics."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from agent_core.domain.identifiers import TaskId
from agent_core.domain.subagents import (
    CompletionGateReceipt,
    DelegationMode,
    EvidenceRef,
    SubagentResultBundle,
    SubagentRole,
    SubagentStatus,
    UsageReceipt,
    research_evidence_gate,
)
from pydantic import ValidationError


def _evidence(evidence_id: str = "ev-1") -> EvidenceRef:
    return EvidenceRef(
        evidence_id=evidence_id,
        uri="file:///workspace/evidence.txt",
        kind="file",
        tool_name="files.read",
        digest="a" * 64,
        observed_at=datetime.now(UTC),
    )


def _receipt(passed: bool = True) -> CompletionGateReceipt:
    return CompletionGateReceipt(
        gate_name="research.evidence",
        passed=passed,
        reason_code="evidence_satisfied" if passed else "no_evidence_collected",
        evaluated_at=datetime.now(UTC),
    )


class TestDelegationMode:
    def test_four_modes_exist(self) -> None:
        assert {mode.value for mode in DelegationMode} == {
            "disabled",
            "auto",
            "required_once",
            "orchestrated",
        }


class TestEvidenceGate:
    def test_zero_evidence_never_passes(self) -> None:
        gate = research_evidence_gate(evidence_count=0, successful_tool_calls=3)
        assert not gate.passed
        assert gate.reason_code == "no_evidence_collected"

    def test_zero_successful_tools_never_passes(self) -> None:
        gate = research_evidence_gate(evidence_count=2, successful_tool_calls=0)
        assert not gate.passed

    def test_evidence_and_tools_pass(self) -> None:
        gate = research_evidence_gate(evidence_count=1, successful_tool_calls=1)
        assert gate.passed
        assert gate.reason_code == "evidence_satisfied"


class TestResultBundle:
    def test_completed_bundle_requires_usage_and_passed_gate(self) -> None:
        with pytest.raises(ValidationError, match="usage"):
            SubagentResultBundle(
                subagent_id="child-1",
                status="completed",
                summary="done",
                gate_receipts=(_receipt(True),),
            )
        with pytest.raises(ValidationError, match="passed gate"):
            SubagentResultBundle(
                subagent_id="child-1",
                status="completed",
                summary="done",
                usage=UsageReceipt(model_calls=1, tool_calls=1),
                gate_receipts=(_receipt(False),),
            )

    def test_bundle_digest_is_deterministic(self) -> None:
        def bundle() -> SubagentResultBundle:
            return SubagentResultBundle(
                child_task_id=TaskId(__import__("uuid").uuid4()),
                subagent_id="child-1",
                status="completed",
                summary="found the proof",
                evidence=(_evidence(),),
                usage=UsageReceipt(model_calls=2, tool_calls=1),
                gate_receipts=(_receipt(True),),
            )

        first = bundle()
        rebuilt = bundle().model_copy(
            update={"child_task_id": first.child_task_id}
        )
        assert first.result_digest == rebuilt.result_digest

    def test_evidence_change_changes_digest(self) -> None:
        base = SubagentResultBundle(
            subagent_id="child-1",
            status="failed",
            summary="no luck",
            gate_receipts=(_receipt(False),),
        )
        with_evidence = base.model_copy(update={"evidence": (_evidence(),)})
        assert base.result_digest != with_evidence.result_digest

    def test_failed_bundle_needs_no_usage(self) -> None:
        bundle = SubagentResultBundle(
            subagent_id="child-1",
            status="failed",
            summary="nothing found",
            gate_receipts=(_receipt(False),),
        )
        assert bundle.status == "failed"


class TestDomainHygiene:
    def test_naive_timestamps_rejected(self) -> None:
        base = _evidence()
        with pytest.raises(ValidationError):
            EvidenceRef(
                evidence_id=base.evidence_id,
                uri=base.uri,
                kind=base.kind,
                tool_name=base.tool_name,
                digest=base.digest,
                observed_at=datetime(2026, 8, 19, 12, 0),
            )

    def test_usage_receipt_requires_activity(self) -> None:
        with pytest.raises(ValidationError):
            UsageReceipt(model_calls=0, tool_calls=0)

    def test_roles_partition_read_only(self) -> None:
        from agent_core.domain.subagents import READ_ONLY_ROLES

        assert SubagentRole.RESEARCHER in READ_ONLY_ROLES
        assert SubagentRole.IMPLEMENTER not in READ_ONLY_ROLES
        assert SubagentStatus.TIMED_OUT.value == "timed_out"
