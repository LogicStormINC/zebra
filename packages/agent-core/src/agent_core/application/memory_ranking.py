from __future__ import annotations

import re
from collections.abc import Sequence

from agent_core.domain.governed_memories import GovernedMemoryEntry
from agent_core.domain.memories import MemoryType

_ALWAYS_RECALL = frozenset({MemoryType.PREFERENCE, MemoryType.PROJECT_RULE})
_LATIN_TOKEN = re.compile(r"[a-z0-9_]+")
_CJK_RUN = re.compile(r"[\u3400-\u9fff]+")


def rank_governed_memories(
    entries: Sequence[GovernedMemoryEntry],
    *,
    query_text: str | None,
    limit: int,
) -> tuple[GovernedMemoryEntry, ...]:
    query = frozenset(memory_text_features(query_text or ""))
    ranked: list[tuple[float, float, str, GovernedMemoryEntry]] = []
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
        ranked.append(
            (
                score,
                entry.record.updated_at.timestamp(),
                str(entry.record.memory_id),
                entry,
            )
        )
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return tuple(item[3] for item in ranked[:limit])


def memory_text_features(text: str, *, limit: int | None = None) -> tuple[str, ...]:
    lowered = text.casefold()
    features = set(_LATIN_TOKEN.findall(lowered))
    for run in _CJK_RUN.findall(lowered):
        features.update(run)
        features.update(run[index : index + 2] for index in range(len(run) - 1))
    ordered = tuple(sorted(features, key=lambda item: (-len(item), item)))
    return ordered if limit is None else ordered[:limit]
