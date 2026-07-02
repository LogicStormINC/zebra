from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
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

_SUPPORTED_TOOL_NAMES = frozenset({"command.run", "files.read", "tests.run"})
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
        seen_keys: set[tuple[str, str, tuple[str, ...], str | None, str]] = set()
        created_at = command.extracted_at or session.updated_at

        for event in events:
            candidates = _candidates_from_tool_event(
                event,
                repo_id=command.repo_id,
                user_id=command.user_id,
                tenant_id=command.tenant_id,
                created_at=created_at,
            )
            for candidate in candidates:
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


def _candidates_from_tool_event(
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
    if tool_name == "files.read":
        output = event.payload.get("output")
        return _doc_candidates_from_file_read(
            event,
            metadata=metadata,
            output=output,
            repo_id=repo_id,
            user_id=user_id,
            tenant_id=tenant_id,
            created_at=created_at,
        )
    command = _command_parts(metadata.get("command"))
    if command is None or _is_sensitive_command(command):
        return ()
    cwd = _normalized_cwd(metadata.get("cwd"))
    preset = _normalized_optional_text(metadata.get("preset"))
    return (
        MemoryRecord(
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
        ),
    )


def _candidate_key(
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


def _doc_candidates_from_file_read(
    event: SessionEvent,
    *,
    metadata: dict[str, object],
    output: object,
    repo_id: str,
    user_id: str | None,
    tenant_id: str | None,
    created_at: datetime,
) -> tuple[MemoryRecord, ...]:
    path = _normalized_optional_text(metadata.get("path"))
    truncated = metadata.get("truncated")
    if (
        path is None
        or Path(path).as_posix() != "AGENTS.md"
        or truncated is not False
        or not isinstance(output, str)
    ):
        return ()
    candidates: list[MemoryRecord] = []
    project_rule = _local_commands_project_rule(output)
    if project_rule is not None:
        candidates.append(
            MemoryRecord(
                memory_id=new_memory_id(),
                memory_type=MemoryType.PROJECT_RULE,
                text=project_rule,
                confidence=0.75,
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
        )
    architecture_fact = _agent_core_dependency_fact(output)
    if architecture_fact is not None:
        candidates.append(
            MemoryRecord(
                memory_id=new_memory_id(),
                memory_type=MemoryType.ARCHITECTURE_FACT,
                text=architecture_fact,
                confidence=0.7,
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
        )
    return tuple(candidates)


def _local_commands_project_rule(output: str) -> str | None:
    lines = output.splitlines()
    commands: list[str] = []
    in_local_commands = False
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("#"):
            heading = line.lstrip("#").strip().lower()
            if heading == "local commands":
                in_local_commands = True
                continue
            if in_local_commands:
                break
        if not in_local_commands or not line.startswith("- "):
            continue
        command = _backticked_token(line)
        if command is not None:
            commands.append(command)
    if not commands:
        return None
    unique_commands = tuple(dict.fromkeys(commands))
    rendered_commands = ", ".join(f"`{command}`" for command in unique_commands)
    # ponytail: only extract the explicit Local Commands section for now.
    # Expand to other governance sections when we have a narrower review
    # policy for doc-derived rules.
    return f"Use the repo default commands: {rendered_commands}."


def _backticked_token(line: str) -> str | None:
    first_tick = line.find("`")
    if first_tick < 0:
        return None
    second_tick = line.find("`", first_tick + 1)
    if second_tick < 0:
        return None
    token = line[first_tick + 1 : second_tick].strip()
    return token or None


def _agent_core_dependency_fact(output: str) -> str | None:
    lines = output.splitlines()
    may_depend = False
    core_isolated = False
    for raw_line in lines:
        line = raw_line.strip()
        if line == "- packages may depend on `agent-core`":
            may_depend = True
        elif line == "- `agent-core` must not depend on other `agent-*` packages":
            core_isolated = True
    if not may_depend or not core_isolated:
        return None
    return (
        "Workspace packages may depend on `agent-core`, but `agent-core` must not "
        "depend on other `agent-*` packages."
    )


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
    preference = _explicit_preference_text(content)
    if preference is None:
        return ()
    return (
        MemoryRecord(
            memory_id=new_memory_id(),
            memory_type=MemoryType.PREFERENCE,
            text=preference,
            confidence=0.7,
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
        ),
    )


def _explicit_preference_text(content: str) -> str | None:
    stripped = content.strip()
    prefix = "preference:"
    if not stripped.lower().startswith(prefix):
        return None
    preference = stripped[len(prefix) :].strip()
    if not preference:
        return None
    return preference
