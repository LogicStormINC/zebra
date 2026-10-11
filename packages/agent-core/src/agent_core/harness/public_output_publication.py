"""Construct bounded narration drafts independently of scheduling and receipt reduction."""

from agent_core.contracts.public_output import EvidenceBasis, PublicOutputPolicy
from agent_core.domain.events import EventActor, EventType
from agent_core.harness.models import HarnessEventDraft


def narration_draft(
    output_id: str,
    kind: str,
    phase: str,
    content: str,
    *,
    attempt: int,
    policy: PublicOutputPolicy,
    meaningful: bool,
    evidence_basis: EvidenceBasis | None,
    evidence_refs: list[str] | None,
    replaces_output_id: str | None,
    origin: str,
    model_call_id: str | None,
) -> HarnessEventDraft:
    payload: dict[str, object] = {
        "schema_version": 1,
        "attempt_number": attempt,
        "output_id": output_id,
        "kind": kind,
        "phase": phase,
        "origin": origin,
        "content": content[: policy.max_characters],
        "status": "complete",
        "meaningful": meaningful,
        "policy_version": policy.version,
        "evidence_refs": evidence_refs or [],
    }
    if replaces_output_id is not None:
        payload["replaces_output_id"] = replaces_output_id
    if evidence_basis is not None:
        payload["evidence_basis"] = evidence_basis
    if model_call_id is not None:
        payload["model_call_id"] = model_call_id
    return HarnessEventDraft(EventType.PUBLIC_OUTPUT, EventActor.HARNESS, payload)
