from __future__ import annotations

from datetime import datetime
from shlex import join as shell_join

from agent_core.application.memory_candidate_doc_sources import (
    doc_candidates_from_file_read,
    doc_refresh_targets_from_file_read,
)
from agent_core.application.memory_candidate_refreshes import MemoryRefreshTarget
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import new_memory_id
from agent_core.domain.memories import (
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)

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
    if tool_name == "files.read":
        return doc_candidates_from_file_read(
            event,
            metadata=metadata,
            output=event.payload.get("output"),
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
            text=_procedure_candidate_text(
                tool_name=tool_name,
                command=command,
                cwd=cwd,
                preset=preset,
            ),
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
    if tool_name == "files.read":
        return doc_refresh_targets_from_file_read(
            metadata=metadata,
            output=event.payload.get("output"),
        )
    command = _command_parts(metadata.get("command"))
    if command is None or _is_sensitive_command(command):
        return ()
    return (
        MemoryRefreshTarget(
            key="procedure:repo_workflow",
            memory_types=(MemoryType.PROCEDURE,),
            reason="stale after procedure refresh",
        ),
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


def _procedure_candidate_text(
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
