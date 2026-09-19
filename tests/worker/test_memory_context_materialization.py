from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.context_materialization import (
    ContextMaterialization,
    ContextMaterializationRequest,
)
from agent_core.domain.governed_memories import (
    GovernedMemoryEntry,
    canonical_governed_memory_content_hash,
    canonical_governed_memory_creation_key,
)
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.memories import (
    MemoryQuery,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)
from agent_core.domain.memory_delivery import MemoryDeliveryScope
from agent_core.ports.agent_memory_gateway import (
    MemoryGatewayHit,
    MemoryGatewaySearchResult,
    MemoryGatewayStatus,
)
from zebra_agent_worker.memory_context_materialization import (
    RankedMemoryContextMaterializer,
)
from zebra_agent_worker.memory_gateway_runtime import MemoryGatewayRuntime

NOW = datetime(2026, 9, 20, tzinfo=UTC)
SESSION_ID = SessionId(UUID("00000000-0000-0000-0000-000000000990"))


class _Base:
    def __init__(self, entries: tuple[GovernedMemoryEntry, ...]) -> None:
        self.entries = entries
        self.seen_limit: int | None = None

    def materialize(self, request: ContextMaterializationRequest) -> ContextMaterialization:
        assert request.memory_query is not None
        self.seen_limit = request.memory_query.limit
        return ContextMaterialization(
            request=request,
            session_revision=request.expected_session_revision,
            memories=self.entries[: request.memory_query.limit],
        )


class _Gateway:
    def __init__(self, ids: tuple[MemoryId, ...]) -> None:
        self.ids = ids
        self.calls = 0

    def search(self, request):  # noqa: ANN001, ANN201
        self.calls += 1
        return MemoryGatewaySearchResult(
            status=MemoryGatewayStatus.SUCCEEDED,
            hits=tuple(
                MemoryGatewayHit(memory_id=memory_id, provider_ref=str(memory_id))
                for memory_id in self.ids
            ),
        )


class _Ledger:
    def revalidate_search_hits(self, scope, hits):  # noqa: ANN001, ANN201
        del scope
        return tuple(
            SimpleNamespace(memory_id=memory_id, provider_ref=provider_ref)
            for memory_id, provider_ref in hits
        )


def test_active_mode_reorders_only_authoritative_candidates_and_backfills() -> None:
    first, second, third = (_entry(index) for index in range(1, 4))
    base = _Base((first, second, third))
    gateway = _Gateway((third.record.memory_id, first.record.memory_id))
    materializer = RankedMemoryContextMaterializer(
        base,
        _runtime(gateway, rollout="active"),
    )

    result = materializer.materialize(_request(limit=3))

    assert base.seen_limit == 50
    assert result.request.memory_query is not None
    assert result.request.memory_query.limit == 3
    assert [entry.record.memory_id for entry in result.memories] == [
        third.record.memory_id,
        first.record.memory_id,
        second.record.memory_id,
    ]


def test_shadow_mode_observes_but_cannot_change_context() -> None:
    first, second = (_entry(index) for index in range(1, 3))
    base = _Base((first, second))
    gateway = _Gateway((second.record.memory_id, first.record.memory_id))
    materializer = RankedMemoryContextMaterializer(
        base,
        _runtime(gateway, rollout="shadow"),
    )

    result = materializer.materialize(_request(limit=2))

    assert gateway.calls == 1
    assert base.seen_limit == 2
    assert result.memories == (first, second)


def test_external_hit_not_in_authoritative_result_cannot_enter_context() -> None:
    first = _entry(1)
    unknown = MemoryId(UUID("00000000-0000-0000-0000-000000000999"))
    materializer = RankedMemoryContextMaterializer(
        _Base((first,)),
        _runtime(_Gateway((unknown,)), rollout="active"),
    )

    result = materializer.materialize(_request(limit=1))

    assert result.memories == (first,)


def _runtime(gateway: _Gateway, *, rollout: str) -> MemoryGatewayRuntime:
    return MemoryGatewayRuntime(
        gateway=gateway,  # type: ignore[arg-type]
        ledger=_Ledger(),  # type: ignore[arg-type]
        authority=object(),  # type: ignore[arg-type]
        scope=MemoryDeliveryScope(
            deployment_namespace="cloud-a",
            scope_digest="a" * 64,
            generation=1,
            revision=0,
        ),
        rollout=rollout,
    )


def _request(*, limit: int) -> ContextMaterializationRequest:
    return ContextMaterializationRequest(
        scope=OpaqueAuthorityScope(authority_issuer="issuer", namespace_id="scope"),
        session_id=SESSION_ID,
        expected_session_revision=1,
        as_of=NOW,
        memory_query=MemoryQuery(
            repo_id="repo-a",
            visibility=MemoryVisibility.REPO,
            text_query="deployment",
            statuses=(MemoryStatus.CONFIRMED,),
            limit=limit,
        ),
    )


def _entry(index: int) -> GovernedMemoryEntry:
    record = MemoryRecord(
        memory_id=MemoryId(UUID(f"00000000-0000-0000-0000-{index:012d}")),
        memory_type=MemoryType.PROCEDURE,
        text=f"deployment memory {index}",
        confidence=1,
        status=MemoryStatus.CONFIRMED,
        visibility=MemoryVisibility.REPO,
        repo_id="repo-a",
        created_at=NOW,
        updated_at=NOW,
    )
    return GovernedMemoryEntry(
        deployment_namespace="cloud-a",
        record=record,
        revision=1,
        creation_key=canonical_governed_memory_creation_key(record),
        content_digest=canonical_governed_memory_content_hash(record),
    )
