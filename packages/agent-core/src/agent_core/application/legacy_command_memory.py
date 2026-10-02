"""Identify the obsolete tool-command generator's exact output, never user prose."""

from __future__ import annotations

from shlex import join as shell_join

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.memories import MemoryRecord, MemoryType


def is_legacy_tool_command_memory(record: MemoryRecord, source: SessionEvent | None) -> bool:
    """Require an exact source-event match before suggesting historical cleanup."""
    if (
        record.memory_type is not MemoryType.PROCEDURE
        or source is None
        or source.event_type is not EventType.TOOL_EXECUTION_COMPLETED
        or source.session_id != record.source_session_id
        or source.sequence != record.source_event_start
        or record.source_event_start != record.source_event_end
        or source.payload.get("status") != "executed"
    ):
        return False
    tool_name = source.payload.get("tool_name")
    if tool_name not in {"command.run", "tests.run"}:
        return False
    metadata = source.payload.get("metadata")
    if not isinstance(metadata, dict):
        return False
    command = metadata.get("command")
    if not isinstance(command, list) or not command or not all(
        isinstance(part, str) and part.strip() for part in command
    ):
        return False
    rendered = shell_join(tuple(part.strip() for part in command))
    cwd = metadata.get("cwd")
    cwd = cwd.strip() if isinstance(cwd, str) and cwd.strip() else "."
    preset = metadata.get("preset")
    preset = preset.strip() if isinstance(preset, str) and preset.strip() else None
    expected = (
        f"Run validation preset '{preset}' as `{rendered}` from `{cwd}`."
        if tool_name == "tests.run" and preset is not None
        else f"Run `{rendered}` from `{cwd}`."
    )
    return record.text == expected
