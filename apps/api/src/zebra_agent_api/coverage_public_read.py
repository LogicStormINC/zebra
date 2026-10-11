"""Ordinary raw output cannot bypass the certified report read boundary."""

from collections.abc import Iterable

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, TaskId
from agent_integrations.ag_ui import AgUiProjectionError
from agent_integrations.coverage_public_events import strict_coverage_events
from agent_storage import ControlPlaneStores

from zebra_agent_api.ag_ui_task_view import canonical_task_view
from zebra_agent_api.responses import ApiResponse


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
    stores: ControlPlaneStores, session_id: SessionId
) -> ApiResponse | None:
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


def coverage_task_read_problem(stores: ControlPlaneStores, task_id: TaskId) -> ApiResponse | None:
    try:
        view = canonical_task_view(stores, task_id)
    except AgUiProjectionError:
        return ApiResponse(
            409,
            {"status": "coverage_identity_unavailable", "reason": "canonical_task_incomplete"},
        )
    return coverage_public_read_problem(item.event for item in view)
