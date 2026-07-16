from __future__ import annotations

from pathlib import Path

from agent_core.application import MemoryReviewAction
from agent_core.domain.memories import MemoryVisibility

from zebra_agent_api.memory_review_execution import (
    _review_memory,
    _review_memory_bulk,
    _review_memory_queue,
)
from zebra_agent_api.memory_review_preview import (
    _preview_memory_queue,
)
from zebra_agent_api.responses import ApiResponse


def review_session_memory(
    *,
    database_path: Path,
    session_id: str,
    memory_id: str,
    payload: dict[str, object],
    action: MemoryReviewAction,
    decision: str,
) -> ApiResponse:
    return _review_memory(
        database_path=database_path,
        memory_id=memory_id,
        payload=payload,
        action=action,
        decision=decision,
        expected_visibility=MemoryVisibility.REPO,
        expected_scope_id=session_id,
    )


def review_user_memory(
    *,
    database_path: Path,
    user_id: str,
    memory_id: str,
    payload: dict[str, object],
    action: MemoryReviewAction,
    decision: str,
) -> ApiResponse:
    return _review_memory(
        database_path=database_path,
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
    tenant_id: str,
    memory_id: str,
    payload: dict[str, object],
    action: MemoryReviewAction,
    decision: str,
) -> ApiResponse:
    return _review_memory(
        database_path=database_path,
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
    session_id: str,
    payload: dict[str, object],
) -> ApiResponse:
    return _review_memory_bulk(
        database_path=database_path,
        payload=payload,
        expected_visibility=MemoryVisibility.REPO,
        expected_scope_id=session_id,
    )


def review_user_memory_bulk(
    *,
    database_path: Path,
    user_id: str,
    payload: dict[str, object],
) -> ApiResponse:
    return _review_memory_bulk(
        database_path=database_path,
        payload=payload,
        expected_visibility=MemoryVisibility.USER,
        expected_scope_id=user_id,
    )


def review_tenant_memory_bulk(
    *,
    database_path: Path,
    tenant_id: str,
    payload: dict[str, object],
) -> ApiResponse:
    return _review_memory_bulk(
        database_path=database_path,
        payload=payload,
        expected_visibility=MemoryVisibility.TENANT,
        expected_scope_id=tenant_id,
    )


def review_session_memory_queue(
    *,
    database_path: Path,
    session_id: str,
    payload: dict[str, object],
) -> ApiResponse:
    return _review_memory_queue(
        database_path=database_path,
        payload=payload,
        expected_visibility=MemoryVisibility.REPO,
        expected_scope_id=session_id,
    )


def review_user_memory_queue(
    *,
    database_path: Path,
    user_id: str,
    payload: dict[str, object],
) -> ApiResponse:
    return _review_memory_queue(
        database_path=database_path,
        payload=payload,
        expected_visibility=MemoryVisibility.USER,
        expected_scope_id=user_id,
    )


def review_tenant_memory_queue(
    *,
    database_path: Path,
    tenant_id: str,
    payload: dict[str, object],
) -> ApiResponse:
    return _review_memory_queue(
        database_path=database_path,
        payload=payload,
        expected_visibility=MemoryVisibility.TENANT,
        expected_scope_id=tenant_id,
    )


def preview_session_memory_queue(
    *,
    database_path: Path,
    session_id: str,
    payload: dict[str, object],
) -> ApiResponse:
    return _preview_memory_queue(
        database_path=database_path,
        payload=payload,
        expected_visibility=MemoryVisibility.REPO,
        expected_scope_id=session_id,
    )


def preview_user_memory_queue(
    *,
    database_path: Path,
    user_id: str,
    payload: dict[str, object],
) -> ApiResponse:
    return _preview_memory_queue(
        database_path=database_path,
        payload=payload,
        expected_visibility=MemoryVisibility.USER,
        expected_scope_id=user_id,
    )


def preview_tenant_memory_queue(
    *,
    database_path: Path,
    tenant_id: str,
    payload: dict[str, object],
) -> ApiResponse:
    return _preview_memory_queue(
        database_path=database_path,
        payload=payload,
        expected_visibility=MemoryVisibility.TENANT,
        expected_scope_id=tenant_id,
    )
