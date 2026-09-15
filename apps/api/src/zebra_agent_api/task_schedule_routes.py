"""Authenticated owner-scoped Task Schedule management routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from agent_core.application.task_schedule_time import next_fire_at
from agent_core.domain.host_authority import HostGrantScopeError
from agent_core.domain.identifiers import TaskScheduleFiringId, TaskScheduleId, new_task_schedule_id
from agent_core.domain.task_schedule_authority import ScheduleOwner
from agent_core.domain.task_schedules import (
    ScheduleMisfirePolicy,
    ScheduleOverlapPolicy,
    ScheduleTrigger,
    TaskSchedule,
    TaskScheduleStatus,
)
from agent_core.ports.task_schedules import (
    TaskScheduleConflictError,
    TaskScheduleFiringStorePort,
    TaskScheduleStorePort,
)
from agent_security import VerifiedHostGrant
from pydantic import TypeAdapter, ValidationError

from zebra_agent_api.extension_turn_admission import CloudExtensionTurnAdmission
from zebra_agent_api.responses import ApiResponse, bad_request, service_unavailable
from zebra_agent_api.task_schedule_api_support import (
    build_schedule_authority,
    expected_version,
    firing_body,
    idempotency_key,
    request_limit,
    schedule_body,
    schedule_path,
)
from zebra_agent_api.task_schedule_template import (
    ValidatedScheduleTemplate,
    validate_schedule_template,
)

if TYPE_CHECKING:
    from zebra_agent_api.app import ZebraAgentApi
    from zebra_agent_api.routes import RouteRequest

_TRIGGER: TypeAdapter[ScheduleTrigger] = TypeAdapter(ScheduleTrigger)
_CREATE_FIELDS = frozenset(
    {
        "title",
        "timezone",
        "trigger",
        "task_template",
        "misfire_policy",
        "misfire_grace_seconds",
        "overlap_policy",
    }
)
_PATCH_FIELDS = frozenset(
    {
        "title",
        "timezone",
        "trigger",
        "task_template",
        "misfire_policy",
        "misfire_grace_seconds",
        "overlap_policy",
    }
)


def handle_schedule_route(
    app: ZebraAgentApi,
    request: RouteRequest,
    *,
    extension_admission: CloudExtensionTurnAdmission | None,
) -> ApiResponse | None:
    if request.path != "/schedules" and not request.path.startswith("/schedules/"):
        return None
    required = "schedule.read" if request.method.upper() == "GET" else "schedule.manage"
    owner = _owner(app, request, required)
    if isinstance(owner, ApiResponse):
        return owner
    if request.path == "/schedules":
        if request.method.upper() == "POST":
            return _create(app, request, owner, extension_admission)
        if request.method.upper() == "GET":
            return _list(app, request, owner)
        return _method_not_allowed()
    parsed = schedule_path(request.path)
    if isinstance(parsed, ApiResponse):
        return parsed
    schedule_id, suffix = parsed
    method = request.method.upper()
    if not suffix and method == "GET":
        return _get(app, schedule_id, owner)
    if not suffix and method == "PATCH":
        return _patch(app, request, schedule_id, owner, extension_admission)
    if not suffix and method == "DELETE":
        return _delete(app, request, schedule_id, owner)
    if suffix in {("pause",), ("resume",)} and method == "POST":
        return _set_activity(app, request, schedule_id, owner, suffix[0])
    if suffix == ("run-now",) and method == "POST":
        return _run_now(app, request, schedule_id, owner)
    if suffix == ("runs",) and method == "GET":
        return _list_runs(app, request, schedule_id, owner)
    if len(suffix) == 2 and suffix[0] == "runs" and method == "GET":
        return _get_run(app, schedule_id, suffix[1], owner)
    return _method_not_allowed()


def _owner(app: ZebraAgentApi, request: RouteRequest, scope: str) -> ScheduleOwner | ApiResponse:
    verified = request.verified_host_grant
    context = request.host_context
    if (
        not isinstance(verified, VerifiedHostGrant)
        or verified.context != context
        or context is None
    ):
        return ApiResponse(403, {"status": "verified_host_grant_required"})
    try:
        context.require_scope(scope)
        if scope == "schedule.manage":
            context.require_scope("agent.run")
    except HostGrantScopeError:
        return ApiResponse(403, {"status": "forbidden", "reason": f"{scope} scope is required"})
    principals = tuple(
        resource.resource_id
        for resource in context.resource_refs
        if resource.resource_type == "principal"
    )
    if app.task_schedule_store is None or app.task_schedule_firing_store is None:
        return service_unavailable(
            status="schedule_storage_unavailable",
            reason="Task Schedule storage is not configured",
        )
    namespace = getattr(app.task_schedule_store, "deployment_namespace", None)
    if not isinstance(namespace, str) or not namespace:
        return service_unavailable(
            status="schedule_storage_unavailable",
            reason="Task Schedule deployment namespace is unavailable",
        )
    if principals != (verified.subject_ref,):
        return ApiResponse(403, {"status": "schedule_owner_invalid"})
    return ScheduleOwner(
        deployment_namespace=namespace,
        tenant_id=context.namespace_id,
        workspace_id=context.workspace_ref,
        principal_id=verified.subject_ref,
        host_app_id=context.host_app_id,
    )


def _create(
    app: ZebraAgentApi,
    request: RouteRequest,
    owner: ScheduleOwner,
    extension_admission: CloudExtensionTurnAdmission | None,
) -> ApiResponse:
    store = _schedule_store(app)
    unknown = sorted(set(request.body or {}) - _CREATE_FIELDS)
    if unknown:
        return bad_request(f"unknown schedule fields: {', '.join(unknown)}")
    body = request.body or {}
    validated = validate_schedule_template(
        app, request, body.get("task_template"), extension_admission
    )
    if isinstance(validated, ApiResponse):
        return validated
    try:
        trigger = _TRIGGER.validate_python(body.get("trigger"))
        moment = datetime.now(UTC)
        timezone_name = str(body.get("timezone", "UTC"))
        first_fire = next_fire_at(trigger, timezone_name=timezone_name, after=moment)
        if first_fire is None:
            return bad_request("trigger does not have a future occurrence")
        schedule_id = new_task_schedule_id()
        assert request.host_context is not None
        authority = build_schedule_authority(
            request.host_context,
            owner,
            schedule_id,
            template=validated.template,
            definition_digest=validated.definition_digest,
            bound_at=moment,
        )
        schedule = TaskSchedule(
            schedule_id=schedule_id,
            owner=owner,
            title=body.get("title", validated.parsed["title"]),
            timezone=timezone_name,
            trigger=trigger,
            task_template=validated.template,
            authority_binding_id=authority.binding_id,
            schedule_version=1,
            next_fire_at=first_fire,
            misfire_policy=body.get("misfire_policy", ScheduleMisfirePolicy.COALESCE_ONE),
            misfire_grace_seconds=body.get("misfire_grace_seconds", 3_600),
            overlap_policy=body.get("overlap_policy", ScheduleOverlapPolicy.FORBID),
            created_at=moment,
            updated_at=moment,
        )
        created = store.create(schedule, authority)
    except (TypeError, ValueError, ValidationError) as exc:
        return bad_request(str(exc))
    except TaskScheduleConflictError:
        return ApiResponse(409, {"status": "schedule_conflict"})
    return ApiResponse(201, schedule_body(created))


def _list(app: ZebraAgentApi, request: RouteRequest, owner: ScheduleOwner) -> ApiResponse:
    store = _schedule_store(app)
    try:
        limit = request_limit(request, default=100)
    except ValueError as exc:
        return bad_request(str(exc))
    schedules = store.list_for_owner(owner, limit=limit)
    include_deleted = (request.query or {}).get("include_deleted") == "true"
    visible = tuple(
        item
        for item in schedules
        if include_deleted or item.status is not TaskScheduleStatus.DELETED
    )
    return ApiResponse(
        200,
        {"count": len(visible), "schedules": [schedule_body(item) for item in visible]},
    )


def _get(app: ZebraAgentApi, schedule_id: TaskScheduleId, owner: ScheduleOwner) -> ApiResponse:
    schedule = _schedule_store(app).get(schedule_id, owner=owner)
    if schedule is None or schedule.status is TaskScheduleStatus.DELETED:
        return _not_found(schedule_id)
    return ApiResponse(200, schedule_body(schedule))


def _patch(
    app: ZebraAgentApi,
    request: RouteRequest,
    schedule_id: TaskScheduleId,
    owner: ScheduleOwner,
    extension_admission: CloudExtensionTurnAdmission | None,
) -> ApiResponse:
    store = _schedule_store(app)
    body = request.body or {}
    unknown = sorted(set(body) - _PATCH_FIELDS - {"schedule_version"})
    if unknown:
        return bad_request(f"unknown schedule patch fields: {', '.join(unknown)}")
    if not (set(body) & _PATCH_FIELDS):
        return bad_request("schedule patch must change at least one field")
    current = store.get(schedule_id, owner=owner)
    if current is None or current.status is TaskScheduleStatus.DELETED:
        return _not_found(schedule_id)
    expected = expected_version(request, body)
    if isinstance(expected, ApiResponse):
        return expected
    validated: ValidatedScheduleTemplate | None = None
    current_authority = None
    if "task_template" in body:
        validation = validate_schedule_template(
            app, request, body["task_template"], extension_admission
        )
        if isinstance(validation, ApiResponse):
            return validation
        validated = validation
        current_authority = store.get_authority(schedule_id, owner=owner)
        if current_authority is None or current_authority.revoked_at is not None:
            return ApiResponse(409, {"status": "schedule_authority_unavailable"})
    updates = dict(current.model_dump())
    try:
        for field in _PATCH_FIELDS:
            if field in body:
                if field == "trigger":
                    updates[field] = _TRIGGER.validate_python(body[field])
                elif field == "task_template":
                    assert validated is not None
                    updates[field] = validated.template
                else:
                    updates[field] = body[field]
        moment = datetime.now(UTC)
        if current.status is TaskScheduleStatus.ACTIVE and ({"trigger", "timezone"} & set(body)):
            updates["next_fire_at"] = next_fire_at(
                updates["trigger"], timezone_name=str(updates["timezone"]), after=moment
            )
        updates.update(schedule_version=current.schedule_version + 1, updated_at=moment)
        replacement = None
        if validated is not None:
            assert request.host_context is not None
            replacement = build_schedule_authority(
                request.host_context,
                owner,
                schedule_id,
                template=validated.template,
                definition_digest=validated.definition_digest,
                bound_at=moment,
            )
            updates["authority_binding_id"] = replacement.binding_id
        changed = TaskSchedule.model_validate(updates)
        if replacement is None:
            saved = store.update(changed, expected_version=expected)
        else:
            assert current_authority is not None
            saved = store.replace_authority(
                changed,
                replacement,
                current_authority.revoke(at=moment),
                expected_version=expected,
                expected_authority_revision=current_authority.binding_revision,
            )
    except (TypeError, ValueError, ValidationError) as exc:
        return bad_request(str(exc))
    except TaskScheduleConflictError:
        return _version_conflict(current)
    return ApiResponse(200, schedule_body(saved))


def _set_activity(
    app: ZebraAgentApi,
    request: RouteRequest,
    schedule_id: TaskScheduleId,
    owner: ScheduleOwner,
    action: str,
) -> ApiResponse:
    store = _schedule_store(app)
    current = store.get(schedule_id, owner=owner)
    if current is None or current.status is TaskScheduleStatus.DELETED:
        return _not_found(schedule_id)
    expected = expected_version(request, request.body or {})
    if isinstance(expected, ApiResponse):
        return expected
    moment = datetime.now(UTC)
    try:
        if action == "pause":
            changed = current.pause(at=moment)
        else:
            resumed_at = next_fire_at(current.trigger, timezone_name=current.timezone, after=moment)
            if resumed_at is None:
                return bad_request("schedule does not have a future occurrence")
            changed = current.resume(next_fire_at=resumed_at, at=moment)
        saved = store.update(changed, expected_version=expected)
    except (TypeError, ValueError, ValidationError) as exc:
        return bad_request(str(exc))
    except TaskScheduleConflictError:
        return _version_conflict(current)
    return ApiResponse(200, schedule_body(saved))


def _delete(
    app: ZebraAgentApi, request: RouteRequest, schedule_id: TaskScheduleId, owner: ScheduleOwner
) -> ApiResponse:
    store = _schedule_store(app)
    current = store.get(schedule_id, owner=owner)
    if current is None or current.status is TaskScheduleStatus.DELETED:
        return _not_found(schedule_id)
    expected = expected_version(request, request.body or {})
    if isinstance(expected, ApiResponse):
        return expected
    authority = store.get_authority(schedule_id, owner=owner)
    if authority is None:
        return service_unavailable(
            status="schedule_authority_missing",
            reason="schedule authority is unavailable",
        )
    moment = datetime.now(UTC)
    try:
        if authority.revoked_at is None:
            store.revoke_authority(
                authority.revoke(at=moment), expected_revision=authority.binding_revision
            )
        deleted = store.update(current.delete(at=moment), expected_version=expected)
    except (TypeError, ValueError, ValidationError) as exc:
        return bad_request(str(exc))
    except TaskScheduleConflictError:
        return _version_conflict(current)
    return ApiResponse(200, schedule_body(deleted))


def _run_now(
    app: ZebraAgentApi, request: RouteRequest, schedule_id: TaskScheduleId, owner: ScheduleOwner
) -> ApiResponse:
    store = _schedule_store(app)
    firing_store = _firing_store(app)
    key = idempotency_key(request)
    if key is None:
        return bad_request("Idempotency-Key header is required")
    schedule = store.get(schedule_id, owner=owner)
    if schedule is None or schedule.status is TaskScheduleStatus.DELETED:
        return _not_found(schedule_id)
    try:
        firing = firing_store.create_manual(schedule, owner=owner, idempotency_key=key)
    except (TypeError, ValueError) as exc:
        return bad_request(str(exc))
    except TaskScheduleConflictError as exc:
        return ApiResponse(409, {"status": "schedule_conflict", "reason": str(exc)})
    return ApiResponse(202, firing_body(firing))


def _list_runs(
    app: ZebraAgentApi, request: RouteRequest, schedule_id: TaskScheduleId, owner: ScheduleOwner
) -> ApiResponse:
    store = _schedule_store(app)
    firing_store = _firing_store(app)
    if store.get(schedule_id, owner=owner) is None:
        return _not_found(schedule_id)
    try:
        limit = request_limit(request, default=50)
    except ValueError as exc:
        return bad_request(str(exc))
    firings = firing_store.list_for_schedule(schedule_id, owner=owner, limit=limit)
    return ApiResponse(
        200,
        {"count": len(firings), "runs": [firing_body(item) for item in firings]},
    )


def _get_run(
    app: ZebraAgentApi,
    schedule_id: TaskScheduleId,
    raw_fire_id: str,
    owner: ScheduleOwner,
) -> ApiResponse:
    firing_store = _firing_store(app)
    try:
        fire_id = TaskScheduleFiringId(UUID(raw_fire_id))
    except ValueError:
        return bad_request("fire_id must be a UUID")
    firing = firing_store.get_for_owner(fire_id, schedule_id=schedule_id, owner=owner)
    if firing is None:
        return ApiResponse(404, {"status": "not_found", "reason": "schedule run does not exist"})
    return ApiResponse(200, firing_body(firing))


def _schedule_store(app: ZebraAgentApi) -> TaskScheduleStorePort:
    assert app.task_schedule_store is not None
    return app.task_schedule_store


def _firing_store(app: ZebraAgentApi) -> TaskScheduleFiringStorePort:
    assert app.task_schedule_firing_store is not None
    return app.task_schedule_firing_store


def _version_conflict(schedule: TaskSchedule) -> ApiResponse:
    return ApiResponse(
        409,
        {"status": "schedule_version_conflict", "current_version": schedule.schedule_version},
    )


def _not_found(schedule_id: TaskScheduleId) -> ApiResponse:
    return ApiResponse(
        404,
        {
            "status": "not_found",
            "reason": "schedule does not exist",
            "schedule_id": str(schedule_id),
        },
    )


def _method_not_allowed() -> ApiResponse:
    return ApiResponse(405, {"status": "method_not_allowed"})
