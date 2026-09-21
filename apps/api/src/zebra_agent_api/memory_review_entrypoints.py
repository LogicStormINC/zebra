from __future__ import annotations

from pathlib import Path

from agent_core.application import MemoryReviewAction, governed_memory_scope_from_events
from agent_core.domain.identifiers import SessionId
from agent_core.domain.memories import MemoryVisibility
from agent_storage import ControlPlaneStores

from zebra_agent_api.memory_review_execution import (
    _review_memory,
    _review_memory_bulk,
    _review_memory_queue,
)
from zebra_agent_api.memory_review_preview import (
    _preview_memory_queue,
)
from zebra_agent_api.responses import ApiResponse, conflict
from zebra_agent_api.session_context import session_workspace_root
from zebra_agent_api.session_identity_read import _parse_session_id


def review_session_memory(
    *,
    database_path: Path,
    stores: ControlPlaneStores,
    session_id: str,
    memory_id: str,
    payload: dict[str, object],
    action: MemoryReviewAction,
    decision: str,
) -> ApiResponse:
    scope = _session_review_scope(stores, session_id)
    if isinstance(scope, ApiResponse):
        return scope
    return _review_memory(
        database_path=database_path,
        stores=stores,
        memory_id=memory_id,
        payload=payload,
        action=action,
        decision=decision,
        expected_visibility=scope[0],
        expected_scope_id=scope[1],
        expected_source_session_id=scope[2],
    )


def review_user_memory(
    *,
    database_path: Path,
    stores: ControlPlaneStores,
    user_id: str,
    memory_id: str,
    payload: dict[str, object],
    action: MemoryReviewAction,
    decision: str,
) -> ApiResponse:
    return _review_memory(
        database_path=database_path,
        stores=stores,
        memory_id=memory_id,
        payload=payload,
        action=action,
        decision=decision,
        expected_visibility=MemoryVisibility.USER,
        expected_scope_id=user_id,
    )


def review_tenant_memory(
    *,
    database_path: Path,
    stores: ControlPlaneStores,
    tenant_id: str,
    memory_id: str,
    payload: dict[str, object],
    action: MemoryReviewAction,
    decision: str,
) -> ApiResponse:
    return _review_memory(
        database_path=database_path,
        stores=stores,
        memory_id=memory_id,
        payload=payload,
        action=action,
        decision=decision,
        expected_visibility=MemoryVisibility.TENANT,
        expected_scope_id=tenant_id,
    )


def review_session_memory_bulk(
    *,
    database_path: Path,
    stores: ControlPlaneStores,
    session_id: str,
    payload: dict[str, object],
) -> ApiResponse:
    scope = _session_review_scope(stores, session_id)
    if isinstance(scope, ApiResponse):
        return scope
    return _review_memory_bulk(
        database_path=database_path,
        stores=stores,
        payload=payload,
        expected_visibility=scope[0],
        expected_scope_id=scope[1],
        expected_source_session_id=scope[2],
    )


def review_user_memory_bulk(
    *,
    database_path: Path,
    stores: ControlPlaneStores,
    user_id: str,
    payload: dict[str, object],
) -> ApiResponse:
    return _review_memory_bulk(
        database_path=database_path,
        stores=stores,
        payload=payload,
        expected_visibility=MemoryVisibility.USER,
        expected_scope_id=user_id,
    )


def review_tenant_memory_bulk(
    *,
    database_path: Path,
    stores: ControlPlaneStores,
    tenant_id: str,
    payload: dict[str, object],
) -> ApiResponse:
    return _review_memory_bulk(
        database_path=database_path,
        stores=stores,
        payload=payload,
        expected_visibility=MemoryVisibility.TENANT,
        expected_scope_id=tenant_id,
    )


def review_session_memory_queue(
    *,
    database_path: Path,
    stores: ControlPlaneStores,
    session_id: str,
    payload: dict[str, object],
) -> ApiResponse:
    scope = _session_review_scope(stores, session_id)
    if isinstance(scope, ApiResponse):
        return scope
    return _review_memory_queue(
        database_path=database_path,
        stores=stores,
        payload=payload,
        expected_visibility=scope[0],
        expected_scope_id=scope[1],
        expected_source_session_id=scope[2],
    )


def review_user_memory_queue(
    *,
    database_path: Path,
    stores: ControlPlaneStores,
    user_id: str,
    payload: dict[str, object],
) -> ApiResponse:
    return _review_memory_queue(
        database_path=database_path,
        stores=stores,
        payload=payload,
        expected_visibility=MemoryVisibility.USER,
        expected_scope_id=user_id,
    )


def review_tenant_memory_queue(
    *,
    database_path: Path,
    stores: ControlPlaneStores,
    tenant_id: str,
    payload: dict[str, object],
) -> ApiResponse:
    return _review_memory_queue(
        database_path=database_path,
        stores=stores,
        payload=payload,
        expected_visibility=MemoryVisibility.TENANT,
        expected_scope_id=tenant_id,
    )


def preview_session_memory_queue(
    *,
    database_path: Path,
    stores: ControlPlaneStores,
    session_id: str,
    payload: dict[str, object],
) -> ApiResponse:
    scope = _session_review_scope(stores, session_id)
    if isinstance(scope, ApiResponse):
        return scope
    return _preview_memory_queue(
        database_path=database_path,
        stores=stores,
        payload=payload,
        expected_visibility=scope[0],
        expected_scope_id=scope[1],
        expected_source_session_id=scope[2],
    )


def _session_review_scope(
    stores: ControlPlaneStores,
    session_id: str,
) -> tuple[MemoryVisibility, str, SessionId] | ApiResponse:
    session_key = _parse_session_id(session_id)
    if isinstance(session_key, ApiResponse):
        return session_key
    events = list(stores.events.list_for_session(session_key))
    workspace_root = session_workspace_root(events)
    if workspace_root is None:
        return conflict(
            session_id=session_id,
            status="memory_unavailable",
            reason="session workspace_root is unavailable",
        )
    scope = governed_memory_scope_from_events(
        events,
        fallback_repo_id=str(workspace_root),
    )
    if scope is None:
        return conflict(
            session_id=session_id,
            status="memory_unavailable",
            reason="session Memory principal scope is ambiguous",
        )
    if scope.user_id is not None:
        return MemoryVisibility.USER, scope.user_id, session_key
    return MemoryVisibility.REPO, session_id, session_key


def preview_user_memory_queue(
    *,
    database_path: Path,
    stores: ControlPlaneStores,
    user_id: str,
    payload: dict[str, object],
) -> ApiResponse:
    return _preview_memory_queue(
        database_path=database_path,
        stores=stores,
        payload=payload,
        expected_visibility=MemoryVisibility.USER,
        expected_scope_id=user_id,
    )


def preview_tenant_memory_queue(
    *,
    database_path: Path,
    stores: ControlPlaneStores,
    tenant_id: str,
    payload: dict[str, object],
) -> ApiResponse:
    return _preview_memory_queue(
        database_path=database_path,
        stores=stores,
        payload=payload,
        expected_visibility=MemoryVisibility.TENANT,
        expected_scope_id=tenant_id,
    )
