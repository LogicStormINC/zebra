"""Ordinary raw output cannot bypass the certified report read boundary."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING
from uuid import UUID

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.ports.stream_source_head import StreamSourceHeadPort
from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointNotReady
from agent_integrations.ag_ui import AgUiProjectionError
from agent_integrations.coverage_public_events import strict_coverage_events
from agent_storage import ControlPlaneStores

from zebra_agent_api.ag_ui_task_view import canonical_task_view
from zebra_agent_api.http_stream_routing import _is_raw_stream_path
from zebra_agent_api.responses import ApiResponse

if TYPE_CHECKING:
    from agent_storage.postgres.stream_proof_batch import StreamProofSnapshot


def coverage_public_read_problem(events: Iterable[SessionEvent]) -> ApiResponse | None:
    if strict_coverage_events(events):
        return ApiResponse(
            409,
            {
                "status": "coverage_report_required",
                "reason": "strict_output_requires_current_certificate",
            },
        )
    return None


def coverage_session_read_problem(
    stores: ControlPlaneStores, session_id: SessionId, *, proof: StreamProofSnapshot | None = None
) -> ApiResponse | None:
    if getattr(stores, "deployment_namespace", None) is not None:
        reader = proof if proof is not None else stores.tasks
        try:
            if proof is not None:
                head = proof.read_stream_source_head(session_id=session_id)
            elif isinstance(reader, StreamSourceHeadPort) and getattr(
                reader, "stream_head_reads_compatible", True
            ):
                head = reader.read_stream_source_head(session_id=session_id)
            else:
                head = None
            if head is not None:
                return _strict_coverage_problem() if head.task.strict_coverage else None
        except (AgUiProjectionError, CheckpointConflict, CheckpointNotReady, ValueError):
            return ApiResponse(
                409,
                {
                    "status": "coverage_identity_unavailable",
                    "reason": "canonical_task_incomplete",
                },
            )
        task_id = (proof if proof is not None else stores.tasks).task_id_for_session(session_id)
        if task_id is None:
            return ApiResponse(
                409,
                {
                    "status": "coverage_identity_unavailable",
                    "reason": "canonical_parent_task_missing",
                },
            )
        return coverage_task_read_problem(stores, task_id, proof=proof)
    events = tuple(stores.events.list_for_session(session_id))
    problem = coverage_public_read_problem(events)
    if problem is not None:
        return problem
    task_id = stores.tasks.task_id_for_session(session_id)
    if task_id is not None:
        return coverage_task_read_problem(stores, task_id)
    # A rebuilding Task index must not detach a durable handoff from its origin.
    lineage = stores.handoffs.get_lineage(session_id)
    if not lineage and any(
        event.event_type is EventType.SESSION_HANDOFF_RECEIVED for event in events
    ):
        return ApiResponse(
            409,
            {
                "status": "coverage_identity_unavailable",
                "reason": "canonical_parent_task_missing",
            },
        )
    return coverage_public_read_problem(
        event for segment in lineage for event in stores.events.list_for_session(segment.session_id)
    )


def coverage_task_read_problem(
    stores: ControlPlaneStores, task_id: TaskId, *, proof: StreamProofSnapshot | None = None
) -> ApiResponse | None:
    try:
        if getattr(stores, "deployment_namespace", None) is not None:
            reader = proof if proof is not None else stores.tasks
            if proof is not None:
                head = proof.read_stream_source_head(task_id=task_id)
                header = head.task if head is not None else None
            elif isinstance(reader, StreamSourceHeadPort) and getattr(
                reader, "stream_head_reads_compatible", True
            ):
                head = reader.read_stream_source_head(task_id=task_id)
                header = head.task if head is not None else None
            else:
                header = stores.tasks.read_task_header(task_id, require_source_coverage=True)
            if header is None or header.strict_coverage is None:
                raise CheckpointNotReady("canonical stream privacy is unavailable")
            if header.strict_coverage:
                return _strict_coverage_problem()
            return None
        view = canonical_task_view(stores, task_id)
    except (AgUiProjectionError, CheckpointConflict, CheckpointNotReady, ValueError):
        return ApiResponse(
            409,
            {"status": "coverage_identity_unavailable", "reason": "canonical_task_incomplete"},
        )
    return coverage_public_read_problem(item.event for item in view)


def cloud_raw_stream_preflight(
    stores: ControlPlaneStores, path: str, *, proof: StreamProofSnapshot | None = None
) -> ApiResponse:
    """HTTP stream admission observes metadata, never the route's full JSON replay."""
    if not _is_raw_stream_path(path):
        return ApiResponse(404, {"status": "not_found"})
    parts = path[1:].split("/")
    try:
        identity = UUID(parts[1])
    except (ValueError, IndexError):
        return ApiResponse(400, {"status": "invalid_request", "reason": "invalid stream ID"})
    if parts[0] == "tasks":
        problem = coverage_task_read_problem(stores, TaskId(identity), proof=proof)
    else:
        problem = coverage_session_read_problem(stores, SessionId(identity), proof=proof)
    return problem or ApiResponse(200, {})


def _strict_coverage_problem() -> ApiResponse:
    return ApiResponse(
        409,
        {
            "status": "coverage_report_required",
            "reason": "strict_output_requires_current_certificate",
        },
    )
