"""Authority-preserving external Memory ranking for cloud Context."""

from __future__ import annotations

from dataclasses import replace

from agent_core.domain.context_materialization import (
    MAX_CONTEXT_MEMORY_ENTRIES,
    ContextMaterialization,
    ContextMaterializationRequest,
)
from agent_core.domain.governed_memories import GovernedMemoryEntry
from agent_core.ports.agent_memory_gateway import (
    AgentMemoryGatewayPort,
    MemoryGatewaySearchRequest,
    MemoryGatewayStatus,
)
from agent_core.ports.context_materialization import ContextMaterializationPort
from agent_storage.postgres.memory_delivery import PostgresMemoryDeliveryLedger

from zebra_agent_worker.memory_gateway_runtime import MemoryGatewayRuntime


class RankedMemoryContextMaterializer(ContextMaterializationPort):
    """Let Redis rank IDs, then admit only PostgreSQL-authorized records."""

    def __init__(
        self,
        base: ContextMaterializationPort,
        runtime: MemoryGatewayRuntime,
    ) -> None:
        self._base = base
        self._runtime = runtime

    def materialize(self, request: ContextMaterializationRequest) -> ContextMaterialization:
        query = request.memory_query
        if query is None or query.text_query is None:
            return self._base.materialize(request)
        expanded = request
        if self._runtime.rollout == "active":
            expanded = replace(
                request,
                memory_query=query.model_copy(update={"limit": MAX_CONTEXT_MEMORY_ENTRIES}),
            )
        authoritative = self._base.materialize(expanded)
        try:
            ranked_ids = _admitted_ranked_ids(
                self._runtime.gateway,
                self._runtime.ledger,
                self._runtime,
                query.text_query,
                limit=MAX_CONTEXT_MEMORY_ENTRIES,
            )
        except Exception:
            return _restore_request(authoritative, request)
        if self._runtime.rollout != "active" or not ranked_ids:
            return _restore_request(authoritative, request)
        by_id = {str(entry.record.memory_id): entry for entry in authoritative.memories}
        ordered = [by_id.pop(memory_id) for memory_id in ranked_ids if memory_id in by_id]
        ordered.extend(
            entry for entry in authoritative.memories if str(entry.record.memory_id) in by_id
        )
        return _restore_request(
            authoritative,
            request,
            memories=tuple(ordered[: query.limit]),
        )


def _admitted_ranked_ids(
    gateway: AgentMemoryGatewayPort,
    ledger: PostgresMemoryDeliveryLedger,
    runtime: MemoryGatewayRuntime,
    query: str,
    *,
    limit: int,
) -> tuple[str, ...]:
    namespace = f"{runtime.scope.scope_digest}:{runtime.scope.generation}"
    result = gateway.search(
        MemoryGatewaySearchRequest(namespace=namespace, query=query, limit=limit)
    )
    if result.status not in {MemoryGatewayStatus.SUCCEEDED, MemoryGatewayStatus.PARTIAL}:
        return ()
    admitted = ledger.revalidate_search_hits(
        runtime.scope,
        ((hit.memory_id, hit.provider_ref) for hit in result.hits),
    )
    return tuple(str(item.memory_id) for item in admitted)


def _restore_request(
    materialized: ContextMaterialization,
    request: ContextMaterializationRequest,
    *,
    memories: tuple[GovernedMemoryEntry, ...] | None = None,
) -> ContextMaterialization:
    selected = materialized.memories if memories is None else memories
    limit = request.memory_query.limit if request.memory_query is not None else 0
    return ContextMaterialization(
        request=request,
        session_revision=materialized.session_revision,
        history=materialized.history,
        history_truncated=materialized.history_truncated,
        truncated_before_sequence=materialized.truncated_before_sequence,
        active_capsule=materialized.active_capsule,
        memories=tuple(selected[:limit]),
    )
