from __future__ import annotations

from dataclasses import dataclass

from agent_core.domain.agent_definition_snapshots import AgentDefinitionSnapshot
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import AgentDefinitionId
from agent_core.domain.memories import MemoryQuery, MemoryStatus, MemoryVisibility


@dataclass(frozen=True, slots=True)
class GovernedMemoryScope:
    """Stable, least-privilege scope shared by Memory writes and reads."""

    repo_id: str
    user_id: str | None = None
    tenant_id: str | None = None
    authority_issuer: str | None = None
    namespace_id: str | None = None
    definition_id: AgentDefinitionId | None = None

    def query(self, *, text_query: str | None = None, limit: int = 50) -> MemoryQuery:
        return MemoryQuery(
            repo_id=self.repo_id,
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            authority_issuer=self.authority_issuer,
            namespace_id=self.namespace_id,
            definition_id=self.definition_id,
            text_query=text_query,
            statuses=(MemoryStatus.CONFIRMED,),
            visibility=(
                MemoryVisibility.USER if self.user_id is not None else MemoryVisibility.REPO
            ),
            limit=limit,
        )


def governed_memory_scope(
    *,
    fallback_repo_id: str,
    host_context: HostContextEnvelope | None = None,
    definition_snapshot: AgentDefinitionSnapshot | None = None,
) -> GovernedMemoryScope | None:
    repo_id = fallback_repo_id
    user_id = None
    tenant_id = None
    if host_context is not None:
        principals = tuple(
            ref.resource_id
            for ref in host_context.resource_refs
            if ref.resource_type == "principal"
        )
        # Host Memory must never silently widen when principal binding is absent
        # or ambiguous. Local execution has no Host context and keeps repo scope.
        if len(principals) != 1:
            return None
        repo_id = host_context.workspace_ref
        user_id = principals[0]
        tenant_id = host_context.namespace_id
    authority_issuer = None
    namespace_id = None
    definition_id = None
    if definition_snapshot is not None:
        authority_issuer = definition_snapshot.authority_issuer
        namespace_id = definition_snapshot.namespace_id
        definition_id = definition_snapshot.definition_id
    return GovernedMemoryScope(
        repo_id=repo_id,
        user_id=user_id,
        tenant_id=tenant_id,
        authority_issuer=authority_issuer,
        namespace_id=namespace_id,
        definition_id=definition_id,
    )


def governed_memory_scope_from_events(
    events: list[SessionEvent] | tuple[SessionEvent, ...],
    *,
    fallback_repo_id: str,
) -> GovernedMemoryScope | None:
    host_context = None
    definition_snapshot = None
    for event in events:
        if event.event_type is not EventType.TASK_PREPARED:
            continue
        raw_host = event.payload.get("host_context")
        raw_definition = event.payload.get("definition_snapshot")
        if isinstance(raw_host, dict):
            try:
                host_context = HostContextEnvelope.model_validate(raw_host)
            except ValueError:
                return None
        if isinstance(raw_definition, dict):
            try:
                definition_snapshot = AgentDefinitionSnapshot.model_validate(raw_definition)
            except ValueError:
                return None
    return governed_memory_scope(
        fallback_repo_id=fallback_repo_id,
        host_context=host_context,
        definition_snapshot=definition_snapshot,
    )
