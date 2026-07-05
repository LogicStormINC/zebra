from datetime import UTC, datetime

import pytest
from agent_core.domain.identifiers import new_memory_id, new_session_id
from agent_core.domain.memories import (
    MemoryQuery,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)


def test_memory_record_requires_scope_for_repo_visibility() -> None:
    with pytest.raises(ValueError, match="repo visibility requires repo_id"):
        MemoryRecord(
            memory_id=new_memory_id(),
            memory_type=MemoryType.PROJECT_RULE,
            text="Use uv and keep package=false at the workspace root.",
            confidence=0.95,
            visibility=MemoryVisibility.REPO,
            created_at=_now(),
            updated_at=_now(),
        )


def test_memory_record_requires_ordered_source_event_range() -> None:
    with pytest.raises(ValueError, match="source event range must be ordered"):
        MemoryRecord(
            memory_id=new_memory_id(),
            memory_type=MemoryType.PROCEDURE,
            text="Run make check before pushing.",
            confidence=0.8,
            visibility=MemoryVisibility.USER,
            user_id="user-1",
            source_session_id=new_session_id(),
            source_event_start=5,
            source_event_end=4,
            created_at=_now(),
            updated_at=_now(),
        )


def test_memory_query_requires_scope() -> None:
    with pytest.raises(ValueError, match="memory query requires at least one scope"):
        MemoryQuery()


def test_memory_query_defaults_to_confirmed_records() -> None:
    query = MemoryQuery(repo_id="zebra-agent")

    assert query.statuses == (MemoryStatus.CONFIRMED,)


def _now() -> datetime:
    return datetime(2026, 7, 2, 18, 0, tzinfo=UTC)
