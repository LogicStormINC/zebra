from __future__ import annotations

from pathlib import Path

from agent_core.domain.memories import MemoryVisibility

from zebra_agent_cli.memory_review_execution import (
    _record_bulk_memory_review,
    _record_memory_review,
    _record_queue_memory_review,
)
from zebra_agent_cli.memory_review_preview import (
    _preview_queue_memory_review,
)


def record_memory_review(
    *,
    database_path: Path,
    session_id: str,
    memory_id: str,
    decision: str,
    operator: str,
    reason: str,
) -> dict[str, object]:
    return _record_memory_review(
        database_path=database_path,
        memory_id=memory_id,
        decision=decision,
        operator=operator,
        reason=reason,
        expected_visibility=MemoryVisibility.REPO,
        expected_scope_id=session_id,
    )


def record_user_memory_review(
    *,
    database_path: Path,
    user_id: str,
    memory_id: str,
    decision: str,
    operator: str,
    reason: str,
) -> dict[str, object]:
    return _record_memory_review(
        database_path=database_path,
        memory_id=memory_id,
        decision=decision,
        operator=operator,
        reason=reason,
        expected_visibility=MemoryVisibility.USER,
        expected_scope_id=user_id,
    )


def record_tenant_memory_review(
    *,
    database_path: Path,
    tenant_id: str,
    memory_id: str,
    decision: str,
    operator: str,
    reason: str,
) -> dict[str, object]:
    return _record_memory_review(
        database_path=database_path,
        memory_id=memory_id,
        decision=decision,
        operator=operator,
        reason=reason,
        expected_visibility=MemoryVisibility.TENANT,
        expected_scope_id=tenant_id,
    )


def record_bulk_memory_review(
    *,
    database_path: Path,
    session_id: str,
    memory_ids: list[str],
    decision: str,
    operator: str,
    reason: str,
) -> dict[str, object]:
    return _record_bulk_memory_review(
        database_path=database_path,
        memory_ids=memory_ids,
        decision=decision,
        operator=operator,
        reason=reason,
        expected_visibility=MemoryVisibility.REPO,
        expected_scope_id=session_id,
    )


def record_bulk_user_memory_review(
    *,
    database_path: Path,
    user_id: str,
    memory_ids: list[str],
    decision: str,
    operator: str,
    reason: str,
) -> dict[str, object]:
    return _record_bulk_memory_review(
        database_path=database_path,
        memory_ids=memory_ids,
        decision=decision,
        operator=operator,
        reason=reason,
        expected_visibility=MemoryVisibility.USER,
        expected_scope_id=user_id,
    )


def record_bulk_tenant_memory_review(
    *,
    database_path: Path,
    tenant_id: str,
    memory_ids: list[str],
    decision: str,
    operator: str,
    reason: str,
) -> dict[str, object]:
    return _record_bulk_memory_review(
        database_path=database_path,
        memory_ids=memory_ids,
        decision=decision,
        operator=operator,
        reason=reason,
        expected_visibility=MemoryVisibility.TENANT,
        expected_scope_id=tenant_id,
    )


def record_queue_memory_review(
    *,
    database_path: Path,
    session_id: str,
    decision: str,
    operator: str,
    reason: str,
) -> dict[str, object]:
    return _record_queue_memory_review(
        database_path=database_path,
        decision=decision,
        operator=operator,
        reason=reason,
        expected_visibility=MemoryVisibility.REPO,
        expected_scope_id=session_id,
    )


def record_queue_user_memory_review(
    *,
    database_path: Path,
    user_id: str,
    decision: str,
    operator: str,
    reason: str,
) -> dict[str, object]:
    return _record_queue_memory_review(
        database_path=database_path,
        decision=decision,
        operator=operator,
        reason=reason,
        expected_visibility=MemoryVisibility.USER,
        expected_scope_id=user_id,
    )


def record_queue_tenant_memory_review(
    *,
    database_path: Path,
    tenant_id: str,
    decision: str,
    operator: str,
    reason: str,
) -> dict[str, object]:
    return _record_queue_memory_review(
        database_path=database_path,
        decision=decision,
        operator=operator,
        reason=reason,
        expected_visibility=MemoryVisibility.TENANT,
        expected_scope_id=tenant_id,
    )


def preview_queue_memory_review(
    *,
    database_path: Path,
    session_id: str,
    decision: str,
    memory_type: str | None,
) -> dict[str, object]:
    return _preview_queue_memory_review(
        database_path=database_path,
        decision=decision,
        memory_type=memory_type,
        expected_visibility=MemoryVisibility.REPO,
        expected_scope_id=session_id,
    )


def preview_queue_user_memory_review(
    *,
    database_path: Path,
    user_id: str,
    decision: str,
    memory_type: str | None,
) -> dict[str, object]:
    return _preview_queue_memory_review(
        database_path=database_path,
        decision=decision,
        memory_type=memory_type,
        expected_visibility=MemoryVisibility.USER,
        expected_scope_id=user_id,
    )


def preview_queue_tenant_memory_review(
    *,
    database_path: Path,
    tenant_id: str,
    decision: str,
    memory_type: str | None,
) -> dict[str, object]:
    return _preview_queue_memory_review(
        database_path=database_path,
        decision=decision,
        memory_type=memory_type,
        expected_visibility=MemoryVisibility.TENANT,
        expected_scope_id=tenant_id,
    )
