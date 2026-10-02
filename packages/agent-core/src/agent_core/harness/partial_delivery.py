"""Publish a truthful status when execution stops before an accepted answer."""

from agent_core.domain.events import EventActor, EventType
from agent_core.harness.evidence_ledger import evidence_ledger
from agent_core.harness.models import HarnessEventDraft

_REASONS = {
    "invalid_tool_request_limit": "Repeated invalid tool requests could not be corrected.",
    "model_call_budget_exhausted": "The available model-call budget was reached.",
    "tool_call_budget_exhausted": "The available tool-call budget was reached.",
    "loop_guard_exhausted": "Repeated calls did not make further progress.",
    "delivery_requirements_unmet": "The result has not met all requested requirements.",
    "verification_required": (
        "Verification status: unverified. The resulting state still needs verification."
    ),
    "acceptance_outcomes_required": "Some requested outcomes remain unverified.",
}


def publish_partial_status(
    events: list[HarnessEventDraft],
    metadata: dict[str, object],
) -> tuple[str, dict[str, object]] | None:
    reason = metadata.get("stop_reason")
    if not isinstance(reason, str) or reason not in _REASONS:
        return None
    if any(event.event_type is EventType.ANSWER_COMMITTED for event in events):
        return None
    ledger = evidence_ledger(events, metadata)
    assessment: dict[str, object] = {
        "status": "partial" if ledger.has_evidence else "blocked",
        "satisfied": ["evidence_collected"] if ledger.has_evidence else [],
        "unmet": [reason],
        "evidence_refs": list(ledger.evidence_refs),
        "media_refs": list(ledger.media_refs),
        "artifact_refs": list(ledger.artifact_refs),
    }
    existing = metadata.get("delivery_assessment")
    if isinstance(existing, dict):
        assessment.update(existing)
    # Never publish the rejected model candidate (it may invent URLs or claim
    # unverified writes). Existing independently delivered content stays intact.
    text = "Task not fully completed. " + _REASONS[reason]
    if ledger.has_evidence:
        text += " Previously returned tool results and delivered content remain available."
    text += " No additional work is running for this attempt."
    attempt = next(
        (
            event.payload.get("attempt_number", 1)
            for event in reversed(events)
            if isinstance(event.payload.get("attempt_number"), int)
        ),
        1,
    )
    events.append(
        HarnessEventDraft(
            event_type=EventType.ANSWER_COMMITTED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": attempt,
                "assistant_message": text,
                "delivery_assessment": assessment,
            },
        )
    )
    return text, {**metadata, "delivery_assessment": assessment}
