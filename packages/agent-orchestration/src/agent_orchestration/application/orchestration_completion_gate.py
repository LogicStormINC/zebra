"""Fixed native read-only policy; no caller-supplied requirements or review claims."""

from typing import Any

from agent_core.domain.bundle_definition import BundleDefinitionSnapshot

from agent_orchestration.application.completion_gate import GateEvaluation, _receipt
from agent_orchestration.application.orchestration_admission import digest

READONLY_POLICY_REF = "evaluation-profile/orchestration-readonly@1"
READONLY_POLICY = {
    "ref": READONLY_POLICY_REF,
    "completion_strategy": "all_success",
    "allowed_tools": ["files.read"],
    "minimum_successful_reads_per_child": 1,
    "minimum_verified_artifacts_per_child": 1,
    "segments_per_child": 1,
    "attempts_per_child": 1,
    "effects_allowed": False,
    "toolchain_required": False,
    "review_required": False,
    "claim": "readonly execution and retained artifact evidence only; no semantic goal proof",
}


def published_completion_policy(definition: Any) -> dict[str, Any] | None:
    """Caller must validate this exact parent Version against the native Registry."""
    if definition.evaluation_profile_ref != READONLY_POLICY_REF:
        return None
    return {
        "semantics": READONLY_POLICY,
        "semantic_digest": digest(READONLY_POLICY),
        "definition_id": str(definition.definition_id),
        "version_id": str(definition.version_id),
        "definition_digest": definition.definition_digest,
        "snapshot_digest": definition.snapshot_digest,
    }


def evaluate_durable_completion(
    run_ref: str,
    *,
    policy: dict[str, Any] | None,
    completion_strategy: str,
    children: list[dict[str, Any]],
) -> GateEvaluation:
    """Evaluate already scoped durable observations, never model summary text."""
    reason = "all_layers_passed"
    if policy is None:
        reason = "gate_policy_unavailable"
    elif policy.get("semantics") != READONLY_POLICY or policy.get("semantic_digest") != digest(
        READONLY_POLICY
    ):
        reason = "gate_policy_conflict"
    elif completion_strategy != "all_success" or any(c["status"] != "completed" for c in children):
        reason = "gate_child_not_successful"
    elif not all(c["effects_confirmed"] and c["readonly"] for c in children):
        reason = "readonly_evidence_conflict"
    elif any(not any(t["successful"] for t in c["tools"]) or not c["artifacts"] for c in children):
        reason = "no_evidence_collected"
    passed = reason == "all_layers_passed"
    return GateEvaluation(
        (_receipt(f"orchestration:{run_ref}.durable", passed, reason, ""),),
        passed,
        False,
        reason,
    )


def definition_binding_matches(actual: str, snapshot: Any) -> bool:
    """Public Bundle admission historically binds Version digest; new children bind Snapshot.

    Both must identify this exact validated native Snapshot. Never rewrite legacy
    binding bytes or accept a digest from a different Version/scope.
    """
    return isinstance(snapshot, BundleDefinitionSnapshot) and actual in {
        snapshot.definition_digest,
        snapshot.snapshot_digest,
    }
