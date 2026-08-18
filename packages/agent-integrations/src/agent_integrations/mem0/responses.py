from __future__ import annotations

from uuid import UUID

from agent_core.domain.identifiers import MemoryId
from agent_core.ports.agent_memory_gateway import MemoryGatewayHit

MAX_PROVIDER_REF_LENGTH = 512


def published_provider_ref(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != 1:
        return None
    result = results[0]
    return provider_ref(result.get("id") if isinstance(result, dict) else None)


def search_hits(
    payload: object,
    encoded_namespace: str,
    *,
    limit: int,
) -> tuple[tuple[MemoryGatewayHit, ...] | None, int, int]:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        return None, 0, 0

    raw_hits = payload["results"]
    hits: list[MemoryGatewayHit] = []
    invalid_count = 0
    for raw_hit in raw_hits[:limit]:
        hit = _search_hit(raw_hit, encoded_namespace)
        if hit is None:
            invalid_count += 1
        else:
            hits.append(hit)
    return tuple(hits), invalid_count, max(0, len(raw_hits) - limit)


def provider_ref(value: object) -> str | None:
    if not isinstance(value, str) or len(value.strip()) > MAX_PROVIDER_REF_LENGTH:
        return None
    try:
        return str(UUID(value.strip()))
    except ValueError:
        return None


def _search_hit(raw_hit: object, encoded_namespace: str) -> MemoryGatewayHit | None:
    if not isinstance(raw_hit, dict) or raw_hit.get("user_id") != encoded_namespace:
        return None
    metadata = raw_hit.get("metadata")
    memory_id = metadata.get("zebra_memory_id") if isinstance(metadata, dict) else None
    parsed_provider_ref = provider_ref(raw_hit.get("id"))
    score = raw_hit.get("score")
    if not isinstance(memory_id, str) or parsed_provider_ref is None:
        return None
    if score is not None and (isinstance(score, bool) or not isinstance(score, int | float)):
        return None
    try:
        return MemoryGatewayHit(
            memory_id=MemoryId(UUID(memory_id)),
            provider_ref=parsed_provider_ref,
            provider_score=float(score) if score is not None else None,
        )
    except ValueError:
        return None
