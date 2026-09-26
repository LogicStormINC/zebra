from datetime import UTC, datetime

from agent_core.application import (
    MemoryCandidateExtractionCommand,
    MemoryCandidateExtractionResult,
    MemoryCandidateExtractionService,
    confirmed_user_profile,
    user_profile_candidates,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import MemoryId, new_memory_id, new_session_id
from agent_core.domain.memories import (
    MemoryQuery,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)
from agent_core.domain.sessions import Session, SessionStatus

NOW = datetime(2026, 9, 21, tzinfo=UTC)


def _memory(memory_type: MemoryType, text: str) -> MemoryRecord:
    return MemoryRecord(
        memory_id=new_memory_id(),
        memory_type=memory_type,
        text=text,
        confidence=0.8,
        status=MemoryStatus.CONFIRMED,
        visibility=MemoryVisibility.USER,
        user_id="user-7",
        repo_id="workspace-a",
        source_session_id=new_session_id(),
        source_event_start=1,
        source_event_end=1,
        created_at=NOW,
        updated_at=NOW,
    )


def test_user_profile_candidates_are_source_bound_and_sensitive_safe() -> None:
    assert user_profile_candidates("我的目标是把 Zebra 接入多个项目")[0].text == (
        "User goal: 把 Zebra 接入多个项目"
    )
    assert user_profile_candidates("这次我的目标是生成临时报告") == ()
    assert user_profile_candidates("我的职责是管理 API key") == ()


def test_confirmed_profile_projects_only_profile_memories() -> None:
    preference = _memory(MemoryType.PREFERENCE, "回复时先给结论")
    background = _memory(MemoryType.EPISODIC, "User background: 云平台负责人")
    goal = _memory(MemoryType.EPISODIC, "User goal: 接入第二个业务系统")
    unrelated = _memory(MemoryType.ARCHITECTURE_FACT, "PostgreSQL 是权威存储")

    profile = confirmed_user_profile((unrelated, goal, preference, background))

    assert [(item.category, item.text) for item in profile] == [
        ("background", "云平台负责人"),
        ("goal", "接入第二个业务系统"),
        ("preference", "回复时先给结论"),
    ]


def test_extraction_proposes_natural_user_background_for_review() -> None:
    result = _extract("我负责公司内部的云端 Agent 平台")

    assert len(result.records) == 1
    assert result.records[0].memory_type is MemoryType.EPISODIC
    assert result.records[0].status is MemoryStatus.CANDIDATE
    assert result.records[0].visibility is MemoryVisibility.USER
    assert result.records[0].text == "User background: 公司内部的云端 Agent 平台"


def test_extraction_does_not_persist_temporary_user_context() -> None:
    assert _extract("这次我负责整理临时测试数据").records == ()


def _extract(content: str) -> MemoryCandidateExtractionResult:
    session = Session(
        session_id=new_session_id(),
        title="Profile candidate",
        status=SessionStatus.COMPLETED,
        created_at=NOW,
        updated_at=NOW,
        current_sequence=5,
    )
    event = SessionEvent.create(
        session_id=session.session_id,
        sequence=4,
        event_type=EventType.USER_MESSAGE_RECEIVED,
        actor=EventActor.USER,
        payload={"content": content},
        created_at=NOW,
    )
    return MemoryCandidateExtractionService(_MemoryStore()).extract(
        session=session,
        events=[event],
        next_sequence=5,
        command=MemoryCandidateExtractionCommand(
            repo_id="zebra-agent",
            user_id="user-7",
            tenant_id="tenant-a",
            extracted_at=NOW,
        ),
    )


class _MemoryStore:
    def __init__(self) -> None:
        self.records: list[MemoryRecord] = []

    def upsert(self, record: MemoryRecord) -> MemoryRecord:
        self.records.append(record)
        return record

    def get(self, memory_id: MemoryId) -> MemoryRecord | None:
        return next(
            (record for record in self.records if record.memory_id == memory_id), None
        )

    def list(self, query: MemoryQuery) -> list[MemoryRecord]:
        return []
