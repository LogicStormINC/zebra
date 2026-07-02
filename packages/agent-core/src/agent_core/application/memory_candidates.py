from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from shlex import join as shell_join

from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_memory_id
from agent_core.domain.memories import (
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.ports.memory_store import MemoryStorePort

_SUPPORTED_TOOL_NAMES = frozenset({"command.run", "tests.run"})
_SHELL_EXECUTABLES = frozenset({"bash", "fish", "powershell", "pwsh", "sh", "zsh"})
_EXFILTRATION_COMMANDS = frozenset({"curl", "nc", "netcat", "scp", "wget"})
_SENSITIVE_PATH_MARKERS = (
    ".env",
    "credential",
    "id_rsa",
    "private_key",
    "secret",
    "token",
)
_SHELL_INJECTION_MARKERS = ("&&", "||", "$(", "`", ";", "|", ">", "<")


@dataclass(frozen=True)
class MemoryCandidateExtractionCommand:
    repo_id: str
    user_id: str | None = None
    tenant_id: str | None = None
    extracted_at: datetime | None = None


@dataclass(frozen=True)
class MemoryCandidateExtractionResult:
    records: tuple[MemoryRecord, ...]
    events: tuple[SessionEvent, ...]


class MemoryCandidateExtractionService:
    def __init__(self, memory_store: MemoryStorePort) -> None:
        self._memory_store = memory_store

    def extract(
        self,
        *,
        session: Session,
        events: list[SessionEvent],
        next_sequence: int,
        command: MemoryCandidateExtractionCommand,
    ) -> MemoryCandidateExtractionResult:
        if session.status is not SessionStatus.COMPLETED:
            raise ValueError("memory candidates can only be extracted from completed sessions")

        records: list[MemoryRecord] = []
        emitted_events: list[SessionEvent] = []
        seen_keys: set[tuple[str, str, tuple[str, ...], str | None]] = set()
        created_at = command.extracted_at or session.updated_at

        for event in events:
            candidate = _candidate_from_tool_event(
                event,
                repo_id=command.repo_id,
                user_id=command.user_id,
                tenant_id=command.tenant_id,
                created_at=created_at,
            )
            if candidate is None:
                continue
            candidate_key = _candidate_key(candidate, event)
            if candidate_key in seen_keys:
                continue
            seen_keys.add(candidate_key)
            stored = self._memory_store.upsert(candidate)
            records.append(stored)
            emitted_events.append(
                SessionEvent.create(
                    session_id=session.session_id,
                    sequence=next_sequence + len(emitted_events),
                    event_type=EventType.MEMORY_CANDIDATE_EXTRACTED,
                    actor=EventActor.HARNESS,
                    payload=_event_payload_for_candidate(stored),
                    created_at=created_at,
                )
            )

        return MemoryCandidateExtractionResult(
            records=tuple(records),
            events=tuple(emitted_events),
        )


def _candidate_from_tool_event(
    event: SessionEvent,
    *,
    repo_id: str,
    user_id: str | None,
    tenant_id: str | None,
    created_at: datetime,
) -> MemoryRecord | None:
    if event.event_type is not EventType.TOOL_EXECUTION_COMPLETED:
        return None
    tool_name = event.payload.get("tool_name")
    status = event.payload.get("status")
    metadata = event.payload.get("metadata")
    if (
        not isinstance(tool_name, str)
        or tool_name not in _SUPPORTED_TOOL_NAMES
        or status != "executed"
        or not isinstance(metadata, dict)
    ):
        return None
    command = _command_parts(metadata.get("command"))
    if command is None or _is_sensitive_command(command):
        return None
    cwd = _normalized_cwd(metadata.get("cwd"))
    preset = _normalized_optional_text(metadata.get("preset"))
    return MemoryRecord(
        memory_id=new_memory_id(),
        memory_type=MemoryType.PROCEDURE,
        text=_candidate_text(tool_name=tool_name, command=command, cwd=cwd, preset=preset),
        confidence=0.9 if tool_name == "tests.run" else 0.8,
        status=MemoryStatus.CANDIDATE,
        visibility=MemoryVisibility.REPO,
        tenant_id=tenant_id,
        user_id=user_id,
        repo_id=repo_id,
        source_session_id=event.session_id,
        source_event_start=event.sequence,
        source_event_end=event.sequence,
        created_at=created_at,
        updated_at=created_at,
    )


def _candidate_key(
    candidate: MemoryRecord,
    event: SessionEvent,
) -> tuple[str, str, tuple[str, ...], str | None]:
    metadata = event.payload.get("metadata")
    if not isinstance(metadata, dict):
        return ("", "", (), None)
    command = _command_parts(metadata.get("command")) or ()
    cwd = _normalized_cwd(metadata.get("cwd"))
    preset = _normalized_optional_text(metadata.get("preset"))
    return (candidate.memory_type.value, cwd, command, preset)


def _event_payload_for_candidate(candidate: MemoryRecord) -> dict[str, object]:
    return {
        "memory_id": str(candidate.memory_id),
        "memory_type": candidate.memory_type.value,
        "status": candidate.status.value,
        "visibility": candidate.visibility.value,
        "text": candidate.text,
        "confidence": candidate.confidence,
        "source_event_start": candidate.source_event_start,
        "source_event_end": candidate.source_event_end,
        "repo_id": candidate.repo_id,
        "user_id": candidate.user_id,
        "tenant_id": candidate.tenant_id,
    }


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


def _candidate_text(
    *,
    tool_name: str,
    command: tuple[str, ...],
    cwd: str,
    preset: str | None,
) -> str:
    rendered_command = shell_join(command)
    if tool_name == "tests.run" and preset is not None:
        return (
            f"Run validation preset '{preset}' as `{rendered_command}` from `{cwd}`."
        )
    return f"Run `{rendered_command}` from `{cwd}`."


def _is_sensitive_command(command: tuple[str, ...]) -> bool:
    executable = command[0].rsplit("/", maxsplit=1)[-1].lower()
    if executable in _SHELL_EXECUTABLES or executable in _EXFILTRATION_COMMANDS:
        return True
    command_text = " ".join(command).lower()
    if any(marker in command_text for marker in _SENSITIVE_PATH_MARKERS):
        return True
    if any(marker in command_text for marker in _SHELL_INJECTION_MARKERS):
        return True
    return False
