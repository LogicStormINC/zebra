"""Recover the current Turn's canonical, monotonically narrowing authority chain."""

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.execution_authority import (
    ExecutionAuthorityDecision,
    ExecutionAuthorityResolutionError,
    ExecutionAuthorityRevalidation,
    ExecutionAuthoritySnapshot,
)


def latest_authority_snapshot(
    events: tuple[SessionEvent, ...] | list[SessionEvent],
) -> ExecutionAuthoritySnapshot | None:
    latest: ExecutionAuthoritySnapshot | None = None
    turn_events = events[current_turn_authority_start(events) :]
    for event in turn_events:
        if event.event_type is EventType.EXECUTION_AUTHORITY_RESOLVED:
            try:
                latest = ExecutionAuthoritySnapshot.model_validate(event.payload)
            except ValueError as exc:
                raise ExecutionAuthorityResolutionError(
                    "durable authority snapshot is invalid"
                ) from exc
            continue
        if event.event_type is not EventType.EXECUTION_AUTHORITY_REVALIDATED:
            continue
        try:
            revalidation = ExecutionAuthorityRevalidation.model_validate(event.payload)
        except ValueError as exc:
            raise ExecutionAuthorityResolutionError(
                "durable authority revalidation is invalid"
            ) from exc
        if revalidation.decision not in {
            ExecutionAuthorityDecision.ALLOWED,
            ExecutionAuthorityDecision.NARROWED,
        }:
            raise ExecutionAuthorityResolutionError(
                "durable authority revalidation denied the Attempt"
            )
        if latest is None or revalidation.prior_snapshot_digest != latest.snapshot_digest:
            raise ExecutionAuthorityResolutionError(
                "durable authority revalidation has no matching prior snapshot"
            )
        if revalidation.effective_snapshot is None:
            raise ExecutionAuthorityResolutionError(
                "durable authority revalidation has no recoverable effective snapshot"
            )
        latest.ensure_not_expanded(revalidation.effective_snapshot)
        latest = revalidation.effective_snapshot
    return latest


def current_turn_authority_start(events: tuple[SessionEvent, ...] | list[SessionEvent]) -> int:
    """A closed Turn starts a new authority chain."""
    terminal = {
        EventType.TURN_COMPLETED,
        EventType.TURN_FAILED,
        EventType.TURN_CANCELLED,
        EventType.SESSION_COMPLETED,
        EventType.SESSION_FAILED,
        EventType.SESSION_CANCELLED,
    }
    return max(
        (index + 1 for index, event in enumerate(events) if event.event_type in terminal), default=0
    )
