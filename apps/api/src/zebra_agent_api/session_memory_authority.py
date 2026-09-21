from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from agent_core.application import GovernedMemoryScope, governed_memory_scope_from_events
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import MemoryId, SessionId
from agent_core.domain.memories import MemoryQuery, MemoryRecord
from agent_core.ports.memory_store import MemoryStorePort
from agent_storage import ControlPlaneStores

from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.session_context import session_workspace_root
from zebra_agent_api.session_read import SessionReadApi as _SessionReadApi


class _ScopedMemoryPayload(dict[str, object]):
    def __init__(
        self,
        payload: dict[str, object],
        scope: GovernedMemoryScope | None,
        rejection: ApiResponse | None = None,
    ) -> None:
        super().__init__(payload)
        self.scope = scope
        self.rejection = rejection


class _ScopedMemoryStore:
    def __init__(self, delegate: MemoryStorePort, scope: GovernedMemoryScope) -> None:
        self._delegate = delegate
        self._scope = scope

    def get(self, memory_id: MemoryId) -> MemoryRecord | None:
        record = self._delegate.get(memory_id)
        return record if record is not None and self._matches(record) else None

    def upsert(self, record: MemoryRecord) -> MemoryRecord:
        raise RuntimeError("session Memory reads cannot mutate Memory")

    def list(self, query: MemoryQuery) -> list[MemoryRecord]:
        return self._delegate.list(
            query.model_copy(
                update={
                    "repo_id": self._scope.repo_id,
                    "user_id": self._scope.user_id,
                    "tenant_id": self._scope.tenant_id,
                    "authority_issuer": self._scope.authority_issuer,
                    "namespace_id": self._scope.namespace_id,
                    "definition_id": self._scope.definition_id,
                }
            )
        )

    def _matches(self, record: MemoryRecord) -> bool:
        return (
            record.repo_id == self._scope.repo_id
            and record.user_id == self._scope.user_id
            and record.tenant_id == self._scope.tenant_id
            and record.authority_issuer == self._scope.authority_issuer
            and record.namespace_id == self._scope.namespace_id
            and record.definition_id == self._scope.definition_id
        )


class _ScopedSessionReadApi:
    def __init__(self, database_path: Path, stores: ControlPlaneStores) -> None:
        self._database_path = database_path
        self._stores = stores

    def __getattr__(self, name: str) -> Any:
        raw = _SessionReadApi(self._database_path, self._stores)
        operation = getattr(raw, name)

        def invoke(*args: object, **kwargs: object) -> object:
            if len(args) >= 2 and isinstance(args[1], _ScopedMemoryPayload):
                payload = args[1]
                if payload.rejection is not None:
                    return payload.rejection
                assert payload.scope is not None
                scoped_stores = replace(
                    self._stores,
                    memories=_ScopedMemoryStore(self._stores.memories, payload.scope),
                )
                scoped_operation = getattr(
                    _SessionReadApi(self._database_path, scoped_stores),
                    name,
                )
                response = scoped_operation(args[0], dict(payload), *args[2:], **kwargs)
                return _bind_response_scope(response, payload.scope)
            return operation(*args, **kwargs)

        return invoke


SessionReadApi = cast(type[_SessionReadApi], _ScopedSessionReadApi)


def _bind_response_scope(response: object, scope: GovernedMemoryScope) -> object:
    if not isinstance(response, ApiResponse):
        return response
    return ApiResponse(
        status_code=response.status_code,
        body=cast(dict[str, object], _replace_repo_scope(response.body, scope.repo_id)),
    )


def _replace_repo_scope(value: object, repo_id: str) -> object:
    if isinstance(value, list):
        return [_replace_repo_scope(item, repo_id) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: _replace_repo_scope(item, repo_id) for key, item in value.items()}
    if "repo_id" in result:
        result["repo_id"] = repo_id
    for key, item in tuple(result.items()):
        if key.endswith("scope_kind") and item == "repo":
            result[f"{key.removesuffix('kind')}id"] = repo_id
    return result


def scoped_memory_payload(
    stores: ControlPlaneStores,
    session_id: str,
    payload: dict[str, object],
) -> dict[str, object]:
    try:
        session_key = SessionId(UUID(session_id))
    except ValueError:
        return payload
    events = list(stores.events.list_for_session(session_key))
    workspace_root = session_workspace_root(events)
    if workspace_root is None:
        return payload
    has_host_context = any(
        event.event_type is EventType.TASK_PREPARED
        and isinstance(event.payload.get("host_context"), dict)
        for event in events
    )
    if not has_host_context:
        return payload
    scope = governed_memory_scope_from_events(
        events,
        fallback_repo_id=str(workspace_root),
    )
    if scope is None or scope.user_id is None:
        return _ScopedMemoryPayload(
            payload,
            None,
            conflict(
                session_id=session_id,
                status="memory_unavailable",
                reason="session Memory principal scope is ambiguous",
            ),
        )
    return _ScopedMemoryPayload(
        {**payload, "user_id": scope.user_id, "tenant_id": scope.tenant_id},
        scope,
    )
