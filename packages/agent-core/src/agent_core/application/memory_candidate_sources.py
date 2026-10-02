from __future__ import annotations

from datetime import datetime

from agent_core.application.memory_candidate_doc_sources import (
    doc_candidates_from_file_read,
    doc_refresh_targets_from_file_read,
)
from agent_core.application.memory_candidate_refreshes import MemoryRefreshTarget
from agent_core.application.memory_directives import (
    MemoryDirectiveAction,
    explicit_memory_directive,
)
from agent_core.application.user_profile_memory import user_profile_candidates
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import new_memory_id
from agent_core.domain.memories import (
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)

_SUPPORTED_TOOL_NAMES = frozenset({"files.read"})


def candidates_from_session_event(
    event: SessionEvent,
    *,
    repo_id: str,
    user_id: str | None,
    tenant_id: str | None,
    created_at: datetime,
) -> tuple[MemoryRecord, ...]:
    if event.event_type is EventType.USER_MESSAGE_RECEIVED:
        return _preference_candidates_from_user_message(
            event,
            repo_id=repo_id,
            user_id=user_id,
            tenant_id=tenant_id,
            created_at=created_at,
        )
    if event.event_type is not EventType.TOOL_EXECUTION_COMPLETED:
        return ()
    tool_name = event.payload.get("tool_name")
    status = event.payload.get("status")
    metadata = event.payload.get("metadata")
    if (
        not isinstance(tool_name, str)
        or tool_name not in _SUPPORTED_TOOL_NAMES
        or status != "executed"
        or not isinstance(metadata, dict)
    ):
        return ()
    return doc_candidates_from_file_read(
        event,
        metadata=metadata,
        output=event.payload.get("output"),
        repo_id=repo_id,
        user_id=user_id,
        tenant_id=tenant_id,
        created_at=created_at,
    )


def refresh_targets_from_session_event(
    event: SessionEvent,
) -> tuple[MemoryRefreshTarget, ...]:
    if event.event_type is not EventType.TOOL_EXECUTION_COMPLETED:
        return ()
    tool_name = event.payload.get("tool_name")
    status = event.payload.get("status")
    metadata = event.payload.get("metadata")
    if (
        not isinstance(tool_name, str)
        or tool_name not in _SUPPORTED_TOOL_NAMES
        or status != "executed"
        or not isinstance(metadata, dict)
    ):
        return ()
    return doc_refresh_targets_from_file_read(
        metadata=metadata,
        output=event.payload.get("output"),
    )


def candidate_key(
    candidate: MemoryRecord,
    event: SessionEvent,
) -> tuple[str, str, tuple[str, ...], str | None, str]:
    metadata = event.payload.get("metadata")
    if not isinstance(metadata, dict):
        return ("", "", (), None, candidate.text)
    command = _command_parts(metadata.get("command")) or ()
    cwd = _normalized_cwd(metadata.get("cwd"))
    preset = _normalized_optional_text(metadata.get("preset"))
    path = _normalized_optional_text(metadata.get("path")) or cwd
    return (candidate.memory_type.value, path, command, preset, candidate.text)


def _command_parts(raw_command: object) -> tuple[str, ...] | None:
    if not isinstance(raw_command, list):
        return None
    command: list[str] = []
    for part in raw_command:
        if not isinstance(part, str):
            return None
        stripped = part.strip()
        if not stripped:
            return None
        command.append(stripped)
    return tuple(command) if command else None


def _normalized_cwd(value: object) -> str:
    if not isinstance(value, str):
        return "."
    stripped = value.strip()
    return stripped or "."


def _normalized_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _preference_candidates_from_user_message(
    event: SessionEvent,
    *,
    repo_id: str,
    user_id: str | None,
    tenant_id: str | None,
    created_at: datetime,
) -> tuple[MemoryRecord, ...]:
    content = event.payload.get("content")
    if not isinstance(content, str):
        return ()
    directive = explicit_memory_directive(content)
    if directive is None:
        if user_id is None:
            return ()
        inferred = user_profile_candidates(content)
        return tuple(
            _user_memory_candidate(
                event,
                text=item.text,
                memory_type=item.memory_type,
                confidence=item.confidence,
                repo_id=repo_id,
                user_id=user_id,
                tenant_id=tenant_id,
                created_at=created_at,
            )
            for item in inferred
        )
    if directive.action is not MemoryDirectiveAction.REMEMBER:
        return ()
    visibility = MemoryVisibility.USER if user_id is not None else MemoryVisibility.REPO
    return (
        _user_memory_candidate(
            event,
            text=directive.text,
            memory_type=directive.memory_type,
            confidence=0.7,
            repo_id=repo_id,
            user_id=user_id,
            tenant_id=tenant_id,
            created_at=created_at,
            visibility=visibility,
        ),
    )


def _user_memory_candidate(
    event: SessionEvent,
    *,
    text: str,
    memory_type: MemoryType,
    confidence: float,
    repo_id: str,
    user_id: str | None,
    tenant_id: str | None,
    created_at: datetime,
    visibility: MemoryVisibility = MemoryVisibility.USER,
) -> MemoryRecord:
    return MemoryRecord(
        memory_id=new_memory_id(),
        memory_type=memory_type,
        text=text,
        confidence=confidence,
        status=MemoryStatus.CANDIDATE,
        visibility=visibility,
        tenant_id=tenant_id,
        user_id=user_id,
        repo_id=repo_id,
        source_session_id=event.session_id,
        source_event_start=event.sequence,
        source_event_end=event.sequence,
        created_at=created_at,
        updated_at=created_at,
    )
