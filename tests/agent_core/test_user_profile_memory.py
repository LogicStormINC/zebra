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


def test_natural_preference_can_be_auto_confirmed_without_remember_directive() -> None:
    candidate = user_profile_candidates("我习惯先看结论再看证据")[0]

    assert candidate.category == "preference"
    assert candidate.memory_type is MemoryType.PREFERENCE
    assert candidate.decision.value == "auto_confirm"
    assert candidate.text == "先看结论再看证据"


def test_portfolio_statement_becomes_review_only_dynamic_candidate() -> None:
    candidate = user_profile_candidates("我现在持有腾讯500股，成本320港币")[0]

    assert candidate.category == "portfolio"
    assert candidate.memory_type is MemoryType.EPISODIC
    assert candidate.decision.value == "review"
    assert candidate.text == "Portfolio position [腾讯]: 500 股, 成本320港币"


def test_temporary_interest_is_not_a_long_term_candidate() -> None:
    assert user_profile_candidates("今天先关注腾讯") == ()


def test_extracts_multiple_durable_facts_from_natural_paragraph() -> None:
    candidates = user_profile_candidates(
        "最近市场波动很大。我现在持有腾讯500股，成本320港币。"
        "我主要关注港股和人工智能。今天先关注腾讯"
    )

    assert [(item.category, item.text) for item in candidates] == [
        ("portfolio", "Portfolio position [腾讯]: 500 股, 成本320港币"),
        ("interest", "User interest: 港股和人工智能"),
    ]


def test_common_natural_phrasings_follow_the_same_safety_policy() -> None:
    background = user_profile_candidates("我从事量化研究")[0]
    interest = user_profile_candidates("我长期关注港股和人工智能")[0]
    preference = user_profile_candidates("I prefer concise answers")[0]
    portfolio = user_profile_candidates("I currently hold AAPL 100 shares at $180")[0]

    assert (background.category, background.decision.value) == ("background", "review")
    assert (interest.category, interest.decision.value) == ("interest", "review")
    assert (preference.category, preference.decision.value) == ("preference", "auto_confirm")
    assert (portfolio.category, portfolio.decision.value) == ("portfolio", "review")
    assert portfolio.text == "Portfolio position [AAPL]: 100 shares, at $180"


def test_confirmed_profile_projects_only_profile_memories() -> None:
    preference = _memory(MemoryType.PREFERENCE, "回复时先给结论")
    background = _memory(MemoryType.EPISODIC, "User background: 云平台负责人")
    goal = _memory(MemoryType.EPISODIC, "User goal: 接入第二个业务系统")
    unrelated = _memory(MemoryType.ARCHITECTURE_FACT, "PostgreSQL 是权威存储")
    interest = _memory(MemoryType.EPISODIC, "User interest: 港股和人工智能")
    portfolio = _memory(
        MemoryType.EPISODIC,
        "Portfolio position [腾讯]: 500 股, 成本320港币",
    )

    profile = confirmed_user_profile(
        (unrelated, goal, preference, background, interest, portfolio)
    )

    assert [(item.category, item.text) for item in profile] == [
        ("background", "云平台负责人"),
        ("goal", "接入第二个业务系统"),
        ("interest", "港股和人工智能"),
        ("portfolio", "腾讯：500 股, 成本320港币"),
        ("preference", "回复时先给结论"),
    ]


def test_extraction_proposes_natural_user_background_for_review() -> None:
    result = _extract("我负责公司内部的云端 Agent 平台")

    assert len(result.records) == 1
    assert result.records[0].memory_type is MemoryType.EPISODIC
    assert result.records[0].status is MemoryStatus.CANDIDATE
    assert result.records[0].visibility is MemoryVisibility.USER
    assert result.records[0].text == "User background: 公司内部的云端 Agent 平台"


def test_extraction_proposes_natural_portfolio_for_review() -> None:
    result = _extract("我持有 AAPL 100 shares, cost $180")

    assert len(result.records) == 1
    assert result.records[0].memory_type is MemoryType.EPISODIC
    assert result.records[0].status is MemoryStatus.CANDIDATE
    assert result.records[0].confidence == 0.8
    assert result.records[0].text == "Portfolio position [AAPL]: 100 shares, cost $180"


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
