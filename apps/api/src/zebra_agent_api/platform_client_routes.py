"""Frontend profile management routes (/platform/v1/frontend-profiles*).

Platform-operator-only management surface (ADR-CLIENT-01). A regular
HostGrant can never publish or bind a profile; every mutation accepts
an ``expected_revision`` CAS token and returns stable problem details.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zebra_agent_api.routes import RouteRequest

from typing import Any

from agent_control_plane.frontend_profiles import (
    FrontendProfileService,
    FrontendProfileServiceError,
)
from agent_core.domain.client_capabilities import (
    ClientCapabilityError,
    FrontendCapabilityProfileVersion,
)

from zebra_agent_api.app import ZebraAgentApi
from zebra_agent_api.platform_operator_auth import (
    PlatformOperatorAuthorizer,
    authorize_platform_operator,
)
from zebra_agent_api.responses import ApiResponse

_PREFIX = "/platform/v1/frontend-profiles"


def _problem(status: int, code: str, detail: str, path: str) -> ApiResponse:
    return ApiResponse(
        status,
        {
            "type": f"https://zebra.invalid/problems/{code}",
            "title": "Frontend profile management rejected",
            "status": status,
            "detail": detail[:512],
            "instance": path,
            "code": code,
        },
    )


def _feature_disabled(path: str) -> ApiResponse:
    return _problem(503, "client_integration_disabled", "client integration is off", path)


def handle_platform_client_route(
    app: ZebraAgentApi,
    request: RouteRequest,
) -> ApiResponse | None:
    if not request.path.startswith(_PREFIX) and not request.path.startswith(
        "/platform/v1/frontend-profile-bindings"
    ):
        return None
    method = request.method.upper()
    authorizer: PlatformOperatorAuthorizer | None = getattr(
        app, "platform_operator_authorizer", None
    )
    _, error = authorize_platform_operator(
        authorizer, request.headers, deployment=app.settings.deployment
    )
    if error is not None:
        return error
    platform = app.client_platform
    if platform is None or platform.frontend_capabilities is None:
        return _feature_disabled(request.path)
    service = FrontendProfileService(platform.frontend_capabilities)
    body = request.body or {}
    try:
        return _dispatch(service, method, request.path, body)
    except FrontendProfileServiceError as exc:
        return _problem(409, "frontend_profile_conflict", str(exc), request.path)
    except ClientCapabilityError as exc:
        return _problem(422, "frontend_profile_invalid", str(exc), request.path)
    except ValueError as exc:
        return _problem(400, "frontend_profile_malformed", str(exc), request.path)


def _dispatch(
    service: FrontendProfileService,
    method: str,
    path: str,
    body: dict[str, Any],
) -> ApiResponse:
    if method == "POST" and path == f"{_PREFIX}/validate":
        profile = FrontendCapabilityProfileVersion.model_validate(body)
        service.validate(profile)
        return ApiResponse(200, {"status": "valid"})
    if method == "POST" and path == _PREFIX:
        profile = FrontendCapabilityProfileVersion.model_validate(body)
        publication = service.publish(profile)
        return ApiResponse(201, publication.__dict__)
    if method == "POST" and path.endswith("/versions"):
        app_id = _app_id_of(path, suffix="/versions")
        profile = FrontendCapabilityProfileVersion.model_validate(
            {**body, "frontend_app_id": app_id}
        )
        publication = service.publish_version(app_id, profile)
        return ApiResponse(201, publication.__dict__)
    if method == "POST" and path == "/platform/v1/frontend-profile-bindings":
        binding = service.bind(
            host_app_id=_required(body, "host_app_id"),
            namespace_id=_required(body, "namespace_id"),
            frontend_app_id=_required(body, "frontend_app_id"),
            revision=int(_required(body, "revision")),
            profile_digest=_required(body, "profile_digest"),
            expected_binding_revision=int(body.get("expected_binding_revision", 0)),
        )
        return ApiResponse(
            201,
            {
                "binding_id": str(binding.binding_id),
                "binding_revision": binding.binding_revision,
            },
        )
    if method == "POST" and path.endswith("/deprecate"):
        app_id = _app_id_of(path, suffix="/deprecate")
        service.deprecate(app_id, int(_required(body, "revision")))
        return ApiResponse(200, {"status": "deprecated"})
    if method == "POST" and path.endswith("/revoke"):
        app_id = _app_id_of(path, suffix="/revoke")
        service.revoke(app_id, int(_required(body, "revision")))
        return ApiResponse(200, {"status": "revoked"})
    if method == "GET":
        app_id, revision = _get_target(path)
        publication = service.get(app_id, revision)
        return ApiResponse(
            200,
            {
                **publication.__dict__,
                "lifecycle": publication.lifecycle.value,
            },
        )
    raise ValueError("unsupported method for frontend profiles")


def _app_id_of(path: str, *, suffix: str) -> str:
    tail = path.removeprefix(f"{_PREFIX}/").removesuffix(suffix).strip()
    if not tail:
        raise ValueError("frontend app id is required")
    return tail


def _get_target(path: str) -> tuple[str, int | None]:
    tail = path.removeprefix(f"{_PREFIX}/")
    if "/revisions/" in tail:
        app_id_text, revision_text = tail.split("/revisions/", 1)
        revision = int(revision_text)
    else:
        app_id_text, revision = tail, None
    app_id = app_id_text.strip()
    if not app_id:
        raise ValueError("frontend app id is required")
    return app_id, revision


def _required(body: dict[str, Any], key: str) -> Any:
    value = body.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{key} is required")
    return value
