"""Validate a scheduled Task through the normal Task admission contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent_core.domain.plugin_snapshots import ExtensionSelection
from agent_core.domain.stream_admission import StreamCapabilities
from agent_core.domain.task_schedule_authority import ScheduledTaskTemplate
from agent_runtime import validate_mcp_capability_selection

from zebra_agent_api.agent_definition_binding import resolve_definition_binding
from zebra_agent_api.extension_task_selection import validate_task_skill_selection
from zebra_agent_api.extension_turn_admission import CloudExtensionTurnAdmission
from zebra_agent_api.responses import ApiResponse, bad_request
from zebra_agent_api.session_binding import NO_CONNECTOR_DIGEST
from zebra_agent_api.session_payload_types import CreateSessionPayload
from zebra_agent_api.session_payloads import parse_create_session_payload

if TYPE_CHECKING:
    from zebra_agent_api.app import ZebraAgentApi
    from zebra_agent_api.routes import RouteRequest


@dataclass(frozen=True)
class ValidatedScheduleTemplate:
    template: ScheduledTaskTemplate
    parsed: CreateSessionPayload
    definition_digest: str


def validate_schedule_template(
    app: ZebraAgentApi,
    request: RouteRequest,
    value: object,
    extension_admission: CloudExtensionTurnAdmission | None,
) -> ValidatedScheduleTemplate | ApiResponse:
    if not isinstance(value, dict):
        return bad_request("task_template must be an object")
    try:
        payload, _, _ = split_schedule_template(value)
    except ValueError as exc:
        return bad_request(str(exc))
    parsed = parse_create_session_payload({**payload, "execute": False})
    if isinstance(parsed, ApiResponse):
        return parsed
    skill_error = validate_task_skill_selection(
        payload, request.verified_host_grant, extension_admission
    )
    if skill_error is not None:
        return skill_error
    try:
        validate_mcp_capability_selection(app.settings.mcp_servers, parsed["mcp_allowlist"])
        template = ScheduledTaskTemplate.model_validate({"payload": value})
    except ValueError as exc:
        return bad_request(str(exc))
    definition = resolve_definition_binding(
        app.agent_registry,
        app.publisher_grants,
        parsed,
        host_context=request.host_context,
        settings=app.settings,
        verified_host_grant=request.verified_host_grant,
    )
    if isinstance(definition, ApiResponse):
        return definition
    return ValidatedScheduleTemplate(
        template=template,
        parsed=parsed,
        definition_digest=(
            definition.definition_digest if definition is not None else NO_CONNECTOR_DIGEST
        ),
    )


def split_schedule_template(
    value: dict[str, object],
) -> tuple[dict[str, object], ExtensionSelection | None, StreamCapabilities | None]:
    payload = dict(value)
    selection = payload.pop("extension_selection", None)
    stream = payload.pop("stream_capabilities", None)
    return (
        payload,
        ExtensionSelection.model_validate(selection) if selection is not None else None,
        StreamCapabilities.model_validate(stream) if stream is not None else None,
    )
