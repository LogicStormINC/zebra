from __future__ import annotations

import re
from collections.abc import Sequence

from agent_core.domain.governed_memories import GovernedMemoryEntry
from agent_core.domain.memories import MemoryType

_ALWAYS_RECALL = frozenset({MemoryType.PREFERENCE})
_STABLE_MEMORY_LIMIT = 2
_LATIN_TOKEN = re.compile(r"[a-z0-9_]+")
_CJK_RUN = re.compile(r"[\u3400-\u9fff]+")
_SYNONYM_GROUPS = (
    ("回答", "回复", "答复", "answer", "reply", "response"),
    ("简短", "简洁", "精简", "brief", "concise", "succinct"),
    ("删除", "移除", "清除", "delete", "remove", "erase"),
    ("仓库", "代码库", "repo", "repository"),
    ("数据库", "数据存储", "database", "datastore"),
)


def rank_governed_memories(
    entries: Sequence[GovernedMemoryEntry],
    *,
    query_text: str | None,
    limit: int,
) -> tuple[GovernedMemoryEntry, ...]:
    query = frozenset(memory_text_features(query_text or ""))
    stable: list[tuple[float, float, str, GovernedMemoryEntry]] = []
    relevant: list[tuple[float, float, str, GovernedMemoryEntry]] = []
    for entry in entries:
        text = frozenset(memory_text_features(entry.record.text))
        always = entry.record.memory_type in _ALWAYS_RECALL
        overlap = len(query & text)
        if not always and query and overlap == 0:
            continue
        score = (100.0 if always else 0.0) + float(overlap)
        normalized_query = " ".join((query_text or "").casefold().split())
        normalized_text = " ".join(entry.record.text.casefold().split())
        if normalized_query and normalized_query in normalized_text:
            score += 20.0
        target = stable if always else relevant
        target.append(
            (
                score,
                entry.record.updated_at.timestamp(),
                str(entry.record.memory_id),
                entry,
            )
        )
    stable.sort(key=lambda item: (-item[0], -item[1], item[2]))
    relevant.sort(key=lambda item: (-item[0], -item[1], item[2]))
    stable_entries = [item[3] for item in stable[: min(_STABLE_MEMORY_LIMIT, limit)]]
    selected = [*stable_entries, *_balanced_relevant(relevant, limit - len(stable_entries))]
    return tuple(selected[:limit])


def _balanced_relevant(
    ranked: list[tuple[float, float, str, GovernedMemoryEntry]], limit: int
) -> list[GovernedMemoryEntry]:
    """Give each relevant Memory type one slot before filling by score."""
    if limit <= 0:
        return []
    selected: list[GovernedMemoryEntry] = []
    selected_ids: set[str] = set()
    seen_types: set[MemoryType] = set()
    for *_, entry in ranked:
        if entry.record.memory_type in seen_types:
            continue
        selected.append(entry)
        selected_ids.add(str(entry.record.memory_id))
        seen_types.add(entry.record.memory_type)
        if len(selected) == limit:
            return selected
    for *_, entry in ranked:
        if str(entry.record.memory_id) in selected_ids:
            continue
        selected.append(entry)
        if len(selected) == limit:
            break
    return selected


def memory_text_features(text: str, *, limit: int | None = None) -> tuple[str, ...]:
    lowered = text.casefold()
    features = set(_LATIN_TOKEN.findall(lowered))
    for run in _CJK_RUN.findall(lowered):
        features.add(run)
        features.update(run[index : index + 2] for index in range(len(run) - 1))
    for group in _SYNONYM_GROUPS:
        if any(term in lowered for term in group):
            features.update(group)
    ordered = tuple(sorted(features, key=lambda item: (-len(item), item)))
    return ordered if limit is None else ordered[:limit]
