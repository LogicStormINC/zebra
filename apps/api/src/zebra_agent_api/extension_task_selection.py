"""Validate explicit root Task Skill selection before any admission side effects."""

from agent_core.ports.extensions import ExtensionNotFoundError, ExtensionSkillAuthorizationError
from agent_security.host_grant import VerifiedHostGrant

from zebra_agent_api.extension_turn_admission import CloudExtensionTurnAdmission
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_skill_inputs import parse_skill_components


def validate_task_skill_selection(
    payload: dict[str, object],
    verified: VerifiedHostGrant | None,
    admission: CloudExtensionTurnAdmission | None,
) -> ApiResponse | None:
    components = parse_skill_components(payload)
    if isinstance(components, ApiResponse):
        return components
    if not components:
        return None
    if admission is None:
        return ApiResponse(503, {"status": "extension_admission_unavailable"})
    if verified is None:
        return ApiResponse(403, {"status": "verified_host_grant_required"})
    try:
        admission.validate_task_skills(verified, components)
    except (ValueError, ExtensionNotFoundError, ExtensionSkillAuthorizationError):
        return ApiResponse(403, {"status": "skill_selection_unavailable"})
    except Exception:
        return ApiResponse(503, {"status": "extension_admission_unavailable"})
    return None
