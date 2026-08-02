"""One-shot authority admission for provider search hits."""

from collections.abc import Iterable
from typing import Any

from agent_core.domain.identifiers import MemoryId
from agent_core.domain.memory_delivery import MemoryDeliveryScope

from agent_storage.postgres.memory_delivery_errors import MemoryDeliveryConflictError
from agent_storage.postgres.memory_delivery_rows import MemoryDeliverySearchAdmission


def revalidate_hits_in_transaction(
    connection: Any,
    namespace: str,
    scope: MemoryDeliveryScope,
    hits: Iterable[tuple[MemoryId, str]],
) -> tuple[MemoryDeliverySearchAdmission, ...]:
    if namespace != scope.deployment_namespace:
        raise MemoryDeliveryConflictError("delivery scope namespace does not match database")
    pairs = _dedupe_hits(hits)
    if not pairs:
        return ()
    values = ", ".join(["(%s, %s, %s)"] * len(pairs))
    hit_parameters = [value for index, pair in enumerate(pairs) for value in (index, *pair)]
    rows = connection.execute(
        f"""
        WITH provider_hits(ordinal, memory_id, provider_ref) AS (VALUES {values})
        SELECT provider_hits.memory_id, provider_hits.provider_ref,
               mapping.memory_revision, mapping.content_digest
        FROM provider_hits
        JOIN memory_delivery_scopes scope_row
         ON scope_row.deployment_namespace = %s
         AND scope_row.scope_digest = %s AND scope_row.generation = %s
         AND scope_row.revision = %s
         AND scope_row.state = 'active'
        JOIN memory_provider_mappings mapping
          ON mapping.deployment_namespace = %s
         AND mapping.scope_digest = scope_row.scope_digest
         AND mapping.generation = scope_row.generation
         AND mapping.memory_id = provider_hits.memory_id
         AND mapping.provider_ref = provider_hits.provider_ref
        JOIN governed_memory_records authority
          ON authority.deployment_namespace = mapping.deployment_namespace
         AND authority.memory_id = mapping.memory_id
         AND authority.status = 'confirmed'
         AND authority.revision = mapping.memory_revision
         AND authority.content_digest = mapping.content_digest
         AND (authority.expires_at IS NULL OR authority.expires_at > transaction_timestamp())
        ORDER BY provider_hits.ordinal
        """,
        [
            *hit_parameters,
            namespace,
            scope.scope_digest,
            scope.generation,
            scope.revision,
            namespace,
        ],
    ).fetchall()
    return tuple(
        MemoryDeliverySearchAdmission(
            memory_id=MemoryId(row["memory_id"]),
            provider_ref=row["provider_ref"],
            memory_revision=int(row["memory_revision"]),
            content_digest=row["content_digest"],
        )
        for row in rows
    )


def _dedupe_hits(hits: Iterable[tuple[MemoryId, str]]) -> tuple[tuple[MemoryId, str], ...]:
    result: list[tuple[MemoryId, str]] = []
    seen: set[tuple[MemoryId, str]] = set()
    for memory_id, provider_ref in hits:
        if not provider_ref or provider_ref != provider_ref.strip():
            raise ValueError("provider_ref must be non-blank and trimmed")
        pair = (memory_id, provider_ref)
        if pair not in seen:
            seen.add(pair)
            result.append(pair)
    if len(result) > 100:
        raise ValueError("search revalidation is limited to 100 hits")
    return tuple(result)
