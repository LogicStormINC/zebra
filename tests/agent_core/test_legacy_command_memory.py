from datetime import UTC, datetime

from agent_core.application.legacy_command_memory import is_legacy_tool_command_memory
from agent_core.application.memory_inventory import serialize_memory_inventory
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, new_memory_id
from agent_core.domain.memories import MemoryRecord, MemoryStatus, MemoryType, MemoryVisibility


def test_legacy_command_warning_requires_exact_tool_provenance() -> None:
    now = datetime(2026, 9, 30, tzinfo=UTC)
    session_id = SessionId("00000000-0000-4000-8000-000000000001")
    source = SessionEvent.create(
        session_id=session_id,
        sequence=7,
        event_type=EventType.TOOL_EXECUTION_COMPLETED,
        actor=EventActor.TOOL,
        payload={
            "tool_name": "command.run",
            "status": "executed",
            "attempt_number": 1,
            "output": "",
            "metadata": {
                "command": ["env", "UV_CACHE_DIR=/tmp/uvcache", "uv", "venv", ".venv-chart"],
                "cwd": ".",
            },
        },
        created_at=now,
    )
    record = MemoryRecord(
        memory_id=new_memory_id(),
        memory_type=MemoryType.PROCEDURE,
        text="Run `env UV_CACHE_DIR=/tmp/uvcache uv venv .venv-chart` from `.`.",
        confidence=0.8,
        status=MemoryStatus.CANDIDATE,
        visibility=MemoryVisibility.USER,
        user_id="user-1",
        repo_id="repo-1",
        source_session_id=session_id,
        source_event_start=7,
        source_event_end=7,
        created_at=now,
        updated_at=now,
    )
    assert is_legacy_tool_command_memory(record, source)
    row = serialize_memory_inventory((record,), (source,))[0]
    assert row["quality_warning"] == "legacy_tool_command"
    corrected = record.model_copy(update={"text": "Use uv for setup."})
    assert not is_legacy_tool_command_memory(corrected, source)
    assert not is_legacy_tool_command_memory(record, None)
    assert not is_legacy_tool_command_memory(
        record.model_copy(update={"source_event_start": 8, "source_event_end": 8}), source
    )
    assert not is_legacy_tool_command_memory(
        record.model_copy(update={"memory_type": MemoryType.PREFERENCE}), source
    )
    failed_source = source.model_copy(update={
        "payload": {**source.payload, "status": "failed"},
    })
    assert not is_legacy_tool_command_memory(record, failed_source)
    validated_source = source.model_copy(update={
        "payload": {
            **source.payload,
            "tool_name": "tests.run",
            "metadata": {
                **source.payload["metadata"],
                "preset": "smoke",
            },
        },
    })
    validated = record.model_copy(update={
        "text": "Run validation preset 'smoke' as "
        "`env UV_CACHE_DIR=/tmp/uvcache uv venv .venv-chart` from `.`."
    })
    assert is_legacy_tool_command_memory(validated, validated_source)
