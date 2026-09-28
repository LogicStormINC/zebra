from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from agent_core.application.memory_directives import safe_memory_text
from agent_core.domain.governed_memories import (
    GovernedMemoryConflictError,
    GovernedMemoryCreate,
)
from agent_core.domain.governed_memory_creation import AdministrativeMemoryCreationRequest
from agent_core.domain.identifiers import TaskId, new_memory_id
from agent_core.domain.memories import (
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)
from agent_core.ports import AdministrativeMutationCAS, GovernedMemoryStorePort
from agent_storage import ControlPlaneStores

from zebra_agent_api.responses import ApiResponse, bad_request, conflict


def create_user_memory(
    *, stores: ControlPlaneStores, user_id: str, payload: dict[str, object]
) -> ApiResponse:
    text = payload.get("text")
    task_id = payload.get("source_task_id")
    operator = payload.get("operator")
    reason = payload.get("reason", "created via API")
    if not isinstance(text, str) or (normalized := safe_memory_text(text)) is None:
        return bad_request("text is blank, sensitive, or outside Memory bounds")
    if not isinstance(task_id, str):
        return bad_request("source_task_id must be a Task UUID")
    if not isinstance(operator, str) or not operator.strip():
        return bad_request("operator must be a non-blank string")
    if not isinstance(reason, str) or not reason.strip():
        return bad_request("reason must be a non-blank string")
    try:
        task = stores.tasks.get_task(TaskId(UUID(task_id)))
    except ValueError:
        task = None
    if task is None:
        return conflict(
            session_id=user_id,
            status="memory_creation_source_unavailable",
            reason="source Agent task is unavailable",
        )
    session = stores.sessions.get_session(task.active_segment_id)
    namespace = getattr(stores, "deployment_namespace", None)
    if session is None or not isinstance(namespace, str):
        return conflict(
            session_id=user_id,
            status="memory_creation_unavailable",
            reason="direct Memory creation requires the authoritative cloud store",
        )
    now = datetime.now(UTC)
    source_sequence = session.current_sequence + 1
    record = MemoryRecord(
        memory_id=new_memory_id(),
        memory_type=MemoryType.PREFERENCE,
        text=normalized,
        confidence=1.0,
        status=MemoryStatus.CANDIDATE,
        visibility=MemoryVisibility.USER,
        user_id=user_id,
        source_session_id=session.session_id,
        source_event_start=source_sequence,
        source_event_end=source_sequence,
        created_at=now,
        updated_at=now,
    )
    request = AdministrativeMemoryCreationRequest.create(
        deployment_namespace=namespace,
        operation_id=f"memory-creation:{session.session_id}:{uuid4()}",
        session_id=session.session_id,
        expected_stream_revision=session.current_sequence,
        memory=GovernedMemoryCreate.from_candidate(record),
        operator=operator.strip(),
        reason=reason.strip(),
        created_at=now,
    )
    try:
        committed = cast(GovernedMemoryStorePort, stores.memories).commit_administrative_creation(
            request,
            authority=AdministrativeMutationCAS(
                deployment_namespace=namespace,
                session_id=session.session_id,
                expected_stream_revision=session.current_sequence,
            ),
        )
    except (GovernedMemoryConflictError, ValueError) as error:
        return conflict(
            session_id=user_id,
            status="memory_creation_conflict",
            reason=str(error),
        )
    return ApiResponse(
        200,
        {
            "memory_id": str(record.memory_id),
            "status": "confirmed",
            "projection_revision": committed.receipt.projection_revision,
        },
    )
