from datetime import UTC, datetime

from agent_core.application import memory_text_features, rank_governed_memories
from agent_core.domain.governed_memories import (
    GovernedMemoryEntry,
    canonical_governed_memory_content_hash,
    canonical_governed_memory_creation_key,
)
from agent_core.domain.identifiers import new_memory_id, new_session_id
from agent_core.domain.memories import (
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)

NOW = datetime(2026, 9, 21, tzinfo=UTC)


def _entry(memory_type: MemoryType, text: str) -> GovernedMemoryEntry:
    record = MemoryRecord(
        memory_id=new_memory_id(),
        memory_type=memory_type,
        text=text,
        confidence=0.8,
        status=MemoryStatus.CONFIRMED,
        visibility=MemoryVisibility.USER,
        tenant_id="tenant-a",
        user_id="user-7",
        repo_id="workspace-a",
        source_session_id=new_session_id(),
        source_event_start=1,
        source_event_end=1,
        created_at=NOW,
        updated_at=NOW,
    )
    return GovernedMemoryEntry(
        deployment_namespace="test",
        record=record,
        revision=1,
        creation_key=canonical_governed_memory_creation_key(record),
        content_digest=canonical_governed_memory_content_hash(record),
    )


def test_ranking_keeps_preferences_and_selects_relevant_chinese_memory() -> None:
    preference = _entry(MemoryType.PREFERENCE, "回复时先给结论")
    relevant = _entry(MemoryType.ARCHITECTURE_FACT, "PostgreSQL 是权威记忆存储")
    irrelevant = _entry(MemoryType.PROCEDURE, "发布前运行前端截图测试")

    ranked = rank_governed_memories(
        (irrelevant, relevant, preference),
        query_text="检查 PostgreSQL 记忆链路",
        limit=8,
    )

    assert preference in ranked
    assert relevant in ranked
    assert irrelevant not in ranked


def test_ranking_bounds_stable_preferences_and_preserves_relevant_type_diversity() -> None:
    preferences = tuple(_entry(MemoryType.PREFERENCE, f"偏好 {index}") for index in range(4))
    architecture = _entry(MemoryType.ARCHITECTURE_FACT, "Agent 使用 PostgreSQL 存储")
    procedure = _entry(MemoryType.PROCEDURE, "Agent 发布前验证 PostgreSQL")

    ranked = rank_governed_memories(
        (*preferences, architecture, procedure),
        query_text="Agent PostgreSQL",
        limit=4,
    )

    assert sum(item.record.memory_type is MemoryType.PREFERENCE for item in ranked) == 2
    assert architecture in ranked
    assert procedure in ranked


def test_ranking_recalls_common_paraphrases_without_single_character_noise() -> None:
    paraphrase = _entry(MemoryType.PROCEDURE, "回复尽量简洁")
    single_character_noise = _entry(MemoryType.ARCHITECTURE_FACT, "回滚发布后检查服务")

    ranked = rank_governed_memories(
        (single_character_noise, paraphrase),
        query_text="回答保持简短",
        limit=4,
    )

    assert ranked == (paraphrase,)
    assert "回复" in memory_text_features("回答保持简短")
    assert "回" not in memory_text_features("回答保持简短")
