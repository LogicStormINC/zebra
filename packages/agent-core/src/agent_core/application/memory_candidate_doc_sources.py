from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agent_core.application.memory_candidate_refreshes import MemoryRefreshTarget
from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import new_memory_id
from agent_core.domain.memories import (
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)


def doc_candidates_from_file_read(
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
            _doc_candidate(
                event,
                memory_type=MemoryType.PROJECT_RULE,
                text=project_rule,
                confidence=0.75,
                repo_id=repo_id,
                user_id=user_id,
                tenant_id=tenant_id,
                created_at=created_at,
            )
        )
    architecture_fact = _agent_core_dependency_fact(output)
    if architecture_fact is not None:
        candidates.append(
            _doc_candidate(
                event,
                memory_type=MemoryType.ARCHITECTURE_FACT,
                text=architecture_fact,
                confidence=0.7,
                repo_id=repo_id,
                user_id=user_id,
                tenant_id=tenant_id,
                created_at=created_at,
            )
        )
    return tuple(candidates)


def doc_refresh_targets_from_file_read(
    *,
    metadata: dict[str, object],
    output: object,
) -> tuple[MemoryRefreshTarget, ...]:
    path = _normalized_optional_text(metadata.get("path"))
    truncated = metadata.get("truncated")
    if (
        path is None
        or Path(path).as_posix() != "AGENTS.md"
        or truncated is not False
        or not isinstance(output, str)
    ):
        return ()
    return (
        MemoryRefreshTarget(
            key="governance:AGENTS.md",
            memory_types=(
                MemoryType.PROJECT_RULE,
                MemoryType.ARCHITECTURE_FACT,
            ),
            reason="stale after AGENTS.md refresh",
        ),
    )


def _doc_candidate(
    event: SessionEvent,
    *,
    memory_type: MemoryType,
    text: str,
    confidence: float,
    repo_id: str,
    user_id: str | None,
    tenant_id: str | None,
    created_at: datetime,
) -> MemoryRecord:
    return MemoryRecord(
        memory_id=new_memory_id(),
        memory_type=memory_type,
        text=text,
        confidence=confidence,
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


def _normalized_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


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
