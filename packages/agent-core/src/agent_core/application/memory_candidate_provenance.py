from __future__ import annotations

from agent_core.application.memory_candidate_sources import candidates_from_session_event
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.memories import MemoryRecord


def refresh_target_applies(
    record: MemoryRecord,
    refresh_target_key: str,
    source_events: list[SessionEvent],
) -> bool:
    if refresh_target_key not in {"procedure:repo_workflow", "governance:AGENTS.md"}:
        return False
    if (
        record.source_session_id is None
        or record.source_event_start is None
        or record.source_event_start != record.source_event_end
    ):
        return False
    source = next(
        (
            event
            for event in source_events
            if event.session_id == record.source_session_id
            and event.sequence == record.source_event_start
        ),
        None,
    )
    if source is None or source.event_type is not EventType.TOOL_EXECUTION_COMPLETED:
        return False
    derived = candidates_from_session_event(
        source,
        repo_id=record.repo_id or "unscoped",
        user_id=record.user_id,
        tenant_id=record.tenant_id,
        created_at=record.created_at,
    )
    normalized = _normalize(record.text)
    return any(
        candidate.memory_type is record.memory_type
        and _normalize(candidate.text) == normalized
        for candidate in derived
    )


def _normalize(text: str) -> str:
    return " ".join(text.strip().split())
