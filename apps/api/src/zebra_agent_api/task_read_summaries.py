"""Read-only watermarked Task usage and bounded attachment pages."""

import base64
import json
from collections.abc import Mapping
from uuid import UUID

from agent_core.domain.identifiers import TaskId
from agent_core.ports.agent_tasks import AgentTaskPort
from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointNotReady
from agent_core.ports.task_read_summaries import (
    TaskAttachmentPage,
    TaskReadSummary,
    TaskReadSummaryPort,
)

from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.task_model_usage import summarize_task_model_usage
from zebra_agent_api.task_responses import task_not_found


def task_projection_pending(task_id: TaskId, reason: str, *, retryable: bool = True) -> ApiResponse:
    return ApiResponse(
        409,
        {
            "task_id": str(task_id),
            "status": "projection_incomplete",
            "reason": reason,
            "code": "projection_not_ready" if retryable else "projection_integrity",
            "retryable": retryable,
        },
    )


def _complete_summary(store: TaskReadSummaryPort, task_id: TaskId) -> TaskReadSummary | ApiResponse:
    try:
        summary = store.read_task_summary(task_id)
    except CheckpointNotReady as exc:
        return task_projection_pending(task_id, str(exc))
    except CheckpointConflict as exc:
        return task_projection_pending(task_id, str(exc), retryable=False)
    if summary is None:
        return task_not_found(str(task_id))
    if not summary.complete:
        return task_projection_pending(task_id, "Task usage summary requires explicit repair")
    return summary


def read_task_usage(store: AgentTaskPort, task_id: TaskId, *, legacy: bool = False) -> ApiResponse:
    if legacy:
        if store.get_task(task_id) is None:
            return task_not_found(str(task_id))
        # ponytail: only the local compatibility profile keeps its historical oracle;
        # cloud composition must use the watermarked, body-free summary below.
        return ApiResponse(
            200,
            {
                "task_id": str(task_id),
                "model_usage": summarize_task_model_usage(store.read_events(task_id, -1)),
            },
        )
    summary = _complete_summary(store, task_id)
    if isinstance(summary, ApiResponse):
        return summary
    return ApiResponse(
        200,
        {
            "task_id": str(task_id),
            "through_sequence": summary.through_sequence,
            "model_usage": summary.model_usage,
            "attachment_count": summary.attachment_count,
            "attachment_bytes": summary.attachment_bytes,
        },
    )


def task_summary_fields(
    store: TaskReadSummaryPort, task_id: TaskId
) -> dict[str, object] | ApiResponse:
    summary = _complete_summary(store, task_id)
    if isinstance(summary, ApiResponse):
        return summary
    if summary.turn_fields is None or summary.active_segment_id is None:
        return task_projection_pending(
            task_id, "Task Turn summary requires explicit bounded preparation"
        )
    try:
        page = store.read_attachment_page(task_id, through_sequence=summary.highwater)
    except CheckpointNotReady as exc:
        return task_projection_pending(task_id, str(exc))
    except CheckpointConflict as exc:
        return task_projection_pending(task_id, str(exc), retryable=False)
    fields: dict[str, object] = {
        "_summary_active_segment_id": str(summary.active_segment_id),
        "read_summary_through_sequence": summary.through_sequence,
        "attachment_count": page.total_count,
        "attachment_bytes": page.total_bytes,
        "attachments_has_more": page.has_more,
        "attachments_next_cursor": _cursor(page),
        "attachments_through_sequence": page.through_sequence,
        **summary.turn_fields,
    }
    if summary.model_usage is not None:
        fields["model_usage"] = summary.model_usage
    if page.entries:
        fields["attachments"] = [entry.attachment.to_mapping() for entry in page.entries]
    return fields


def _cursor(page: TaskAttachmentPage) -> str | None:
    if not page.has_more:
        return None
    data = json.dumps(
        {
            "v": 1,
            "task_id": str(page.task_id),
            "through_sequence": page.through_sequence,
            "after_ordinal": page.next_ordinal,
        },
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _decode_cursor(raw: str, task_id: TaskId) -> tuple[int, int]:
    if not raw or len(raw) > 512:
        raise ValueError("invalid attachment cursor")
    try:
        data = json.loads(
            base64.b64decode(raw + "=" * (-len(raw) % 4), altchars=b"-_", validate=True)
        )
    except (ValueError, UnicodeError) as exc:
        raise ValueError("invalid attachment cursor") from exc
    if (
        not isinstance(data, dict)
        or set(data) != {"v", "task_id", "through_sequence", "after_ordinal"}
        or type(data["v"]) is not int
        or data["v"] != 1
        or UUID(data["task_id"]) != task_id
        or type(data["through_sequence"]) is not int
        or not -1 <= data["through_sequence"] <= 2**63 - 1
        or type(data["after_ordinal"]) is not int
        or not 0 <= data["after_ordinal"] <= 2**63 - 1
    ):
        raise ValueError("attachment cursor belongs to another Task or invalid window")
    return data["after_ordinal"], data["through_sequence"]


def read_task_attachments(
    store: TaskReadSummaryPort,
    task_id: TaskId,
    query: Mapping[str, str],
) -> ApiResponse:
    try:
        after, through = (
            _decode_cursor(query["cursor"], task_id) if "cursor" in query else (-1, None)
        )
        limit = int(query.get("limit", "256"))
        budget = int(query.get("max_bytes", "1048576"))
        if store.read_task_summary(task_id) is None:
            return task_not_found(str(task_id))
        page = store.read_attachment_page(
            task_id,
            after,
            through_sequence=through,
            limit=limit,
            max_bytes=budget,
        )
    except CheckpointNotReady as exc:
        return task_projection_pending(task_id, str(exc))
    except CheckpointConflict as exc:
        return task_projection_pending(task_id, str(exc), retryable=False)
    except (ValueError, TypeError, AttributeError) as exc:
        return ApiResponse(
            400, {"task_id": str(task_id), "status": "invalid_request", "reason": str(exc)}
        )
    return ApiResponse(
        200,
        {
            "task_id": str(task_id),
            "through_sequence": page.through_sequence,
            "attachments": [entry.attachment.to_mapping() for entry in page.entries],
            "attachment_count": page.total_count,
            "attachment_bytes": page.total_bytes,
            "byte_count": page.byte_count,
            "has_more": page.has_more,
            "next_cursor": _cursor(page),
        },
    )
