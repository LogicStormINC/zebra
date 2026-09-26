from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from agent_core.application.memory_directives import safe_memory_text
from agent_core.domain.governed_memories import (
    GovernedMemoryConflictError,
    GovernedMemoryCreate,
    GovernedMemoryEntry,
    GovernedMemoryManagementContext,
)
from agent_core.domain.governed_memory_operations import (
    AdministrativeMemoryReplacementRequest,
)
from agent_core.domain.identifiers import MemoryId, new_memory_id
from agent_core.domain.memories import MemoryStatus, MemoryType, MemoryVisibility
from agent_core.ports import AdministrativeMutationCAS, GovernedMemoryStorePort
from agent_storage import ControlPlaneStores

from zebra_agent_api.memory_review_serialization import _not_found_response, _scope_matches
from zebra_agent_api.responses import ApiResponse, bad_request, conflict


def replace_user_memory(
    *, stores: ControlPlaneStores, user_id: str, memory_id: str, payload: dict[str, object]
) -> ApiResponse:
    text = payload.get("text")
    if not isinstance(text, str):
        return bad_request("text must be a string")
    normalized = safe_memory_text(text)
    if normalized is None:
        return bad_request("text is blank, sensitive, or outside Memory bounds")
    operator = payload.get("operator")
    reason = payload.get("reason", "corrected via API")
    if not isinstance(operator, str) or not operator.strip():
        return bad_request("operator must be a non-blank string")
    if not isinstance(reason, str) or not reason.strip():
        return bad_request("reason must be a non-blank string")
    try:
        target_id = MemoryId(UUID(memory_id))
    except ValueError:
        return _not_found_response(
            memory_id=memory_id,
            visibility=MemoryVisibility.USER,
            scope_id=user_id,
        )
    namespace = getattr(stores, "deployment_namespace", None)
    if not isinstance(namespace, str):
        return conflict(
            session_id=user_id,
            status="memory_replacement_unavailable",
            reason="direct Memory correction requires the authoritative cloud store",
        )
    memory_store = cast(GovernedMemoryStorePort, stores.memories)
    authority = memory_store.get_authority(
        target_id,
        management=GovernedMemoryManagementContext(
            operation_id=f"memory-replacement-read:{uuid4()}",
            operator=operator.strip(),
            reason=reason.strip(),
        ),
    )
    if not isinstance(authority, GovernedMemoryEntry) or not _scope_matches(
        authority.record, MemoryVisibility.USER, user_id
    ):
        return _not_found_response(
            memory_id=memory_id,
            visibility=MemoryVisibility.USER,
            scope_id=user_id,
        )
    record = authority.record
    if record.status is not MemoryStatus.CONFIRMED or record.source_session_id is None:
        return conflict(
            session_id=user_id,
            status="memory_replacement_conflict",
            reason="only confirmed source-bound Memory can be corrected",
        )
    replacement_text = _replacement_text(record.memory_type, record.text, normalized)
    if replacement_text is None:
        return conflict(
            session_id=user_id,
            status="memory_replacement_unsupported",
            reason="this Memory type must be replaced through its source workflow",
        )
    session = stores.sessions.get_session(record.source_session_id)
    if session is None:
        return _not_found_response(
            memory_id=memory_id,
            visibility=MemoryVisibility.USER,
            scope_id=user_id,
        )
    now = datetime.now(UTC)
    replacement_record = record.model_copy(
        update={
            "memory_id": new_memory_id(),
            "text": replacement_text,
            "confidence": 1.0,
            "status": MemoryStatus.CANDIDATE,
            "superseded_by": None,
            "expires_at": None,
            "created_at": now,
            "updated_at": now,
        }
    )
    request = AdministrativeMemoryReplacementRequest.create(
        deployment_namespace=namespace,
        operation_id=f"memory-replacement:{session.session_id}:{uuid4()}",
        session_id=session.session_id,
        expected_stream_revision=session.current_sequence,
        memory_id=record.memory_id,
        expected_revision=authority.revision,
        replacement=GovernedMemoryCreate.from_candidate(replacement_record),
        operator=operator.strip(),
        reason=reason.strip(),
        created_at=now,
    )
    try:
        committed = memory_store.commit_administrative_replacement(
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
            status="memory_replacement_conflict",
            reason=str(error),
        )
    return ApiResponse(
        200,
        {
            "memory_id": str(replacement_record.memory_id),
            "replaced_memory_id": memory_id,
            "status": "confirmed",
            "projection_revision": committed.receipt.projection_revision,
        },
    )


def _replacement_text(memory_type: MemoryType, old_text: str, text: str) -> str | None:
    if memory_type is MemoryType.PREFERENCE:
        return text
    if memory_type is MemoryType.EPISODIC:
        for prefix in ("User background: ", "User goal: "):
            if old_text.startswith(prefix):
                return f"{prefix}{text}"
    return None
