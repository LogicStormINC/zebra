"""Request parsing for session memory management."""

from datetime import UTC, datetime

from agent_core.domain.memories import MemoryType

from zebra_agent_api.responses import ApiResponse, bad_request
from zebra_agent_api.session_payload_types import MemoryOverviewPayload, QueueSweepPreviewPayload


def parse_memory_overview_payload(
    payload: dict[str, object],
) -> MemoryOverviewPayload | ApiResponse:
    user_id = payload.get("user_id")
    if user_id is not None and (not isinstance(user_id, str) or not user_id.strip()):
        return bad_request("user_id must be a non-blank string when provided")

    tenant_id = payload.get("tenant_id")
    if tenant_id is not None and (not isinstance(tenant_id, str) or not tenant_id.strip()):
        return bad_request("tenant_id must be a non-blank string when provided")

    as_of = payload.get("as_of")
    parsed_as_of: datetime | None = None
    if as_of is not None:
        if not isinstance(as_of, str) or not as_of.strip():
            return bad_request("as_of must be a non-blank ISO 8601 string when provided")
        try:
            parsed_as_of = datetime.fromisoformat(as_of.strip())
        except ValueError:
            return bad_request("as_of must be a valid ISO 8601 datetime when provided")
        if parsed_as_of.tzinfo is None:
            return bad_request("as_of must include timezone information")
        parsed_as_of = parsed_as_of.astimezone(UTC)

    return {
        "user_id": user_id.strip() if isinstance(user_id, str) else None,
        "tenant_id": tenant_id.strip() if isinstance(tenant_id, str) else None,
        "as_of": parsed_as_of,
    }


def parse_queue_sweep_preview_payload(
    payload: dict[str, object],
) -> QueueSweepPreviewPayload | ApiResponse:
    decision = payload.get("decision")
    if decision not in {"confirm", "expire"}:
        return bad_request("decision must be either 'confirm' or 'expire'")

    memory_type = payload.get("memory_type")
    if memory_type is not None:
        if not isinstance(memory_type, str) or not memory_type.strip():
            return bad_request("memory_type must be a non-blank string when provided")
        try:
            MemoryType(memory_type.strip())
        except ValueError:
            return bad_request("memory_type is not supported")
        memory_type = memory_type.strip()

    return {"decision": decision, "memory_type": memory_type}
