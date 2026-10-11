"""Strict summaries expose lifecycle, never a second candidate-output channel."""

from agent_core.domain.identifiers import SessionId
from agent_storage import ControlPlaneStores

from zebra_agent_api.coverage_public_read import coverage_session_read_problem

_LIFECYCLE_FIELDS = frozenset(
    {
        "session_id",
        "task_id",
        "status",
        "task_status",
        "current_sequence",
        "active_segment_sequence",
        "active_segment_id",
        "created_at",
        "updated_at",
        "interaction_mode",
        "turn_id",
        "current_turn_status",
    }
)


def coverage_public_summary(
    stores: ControlPlaneStores, session_id: SessionId, body: dict[str, object]
) -> dict[str, object]:
    problem = coverage_session_read_problem(stores, session_id)
    if problem is None:
        return body
    # ponytail: a whitelist also closes future summary additions by default.
    public = {key: value for key, value in body.items() if key in _LIFECYCLE_FIELDS}
    public.update(title="全量数据处理", output_status=problem.body["status"])
    return public
