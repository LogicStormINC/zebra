"""HTTP composition of a trusted watchdog stop; never executes/replays a Run."""

from typing import Any
from uuid import UUID

from agent_core.domain.host_authority import HostContextEnvelope
from agent_security.host_grant import VerifiedHostGrant
from agent_storage.postgres.force_stops import PostgresForceStops
from psycopg import Error

from zebra_agent_api.idempotency import scoped_idempotency_key
from zebra_agent_api.responses import ApiResponse


def force_stop_task(
    app: Any,
    task: str,
    context: HostContextEnvelope | None,
    key: str | None,
    *,
    read: bool = False,
    verified: VerifiedHostGrant | None = None,
    payload: dict[str, Any] | None = None,
) -> ApiResponse:
    if verified is None or verified.context != context:
        return ApiResponse(403, {"status": "force_stop_requires_verified_host_grant"})
    if not read:
        if (
            not isinstance(key, str)
            or not key.strip()
            or len(key) > 240
            or any(ord(char) < 32 or ord(char) > 126 for char in key)
        ):
            return ApiResponse(400, {"status": "invalid_force_stop_idempotency_key"})
        if payload is not None and (set(payload) != {"force"} or payload["force"] is not True):
            return ApiResponse(400, {"status": "invalid_force_stop"})
    control = app.cloud_control
    if control is None or context is None:
        return ApiResponse(403, {"status": "force_stop_requires_cloud_host_authority"})
    try:
        store = PostgresForceStops(
            control._database._dsn, deployment_namespace=control.deployment_namespace
        )
        task_id = UUID(task)
        result = (
            store.status(task_id, context, authority_issuer=verified.authority_issuer)
            if read
            else store.request(
                task_id,
                context,
                scoped_idempotency_key(key, context) or "",
                authority_issuer=verified.authority_issuer,
            )
        )
    except (Error, RuntimeError):
        return ApiResponse(
            503,
            {
                "status": "force_stop_unavailable",
                "request_accepted": None,
                "resources_released": False,
            },
        )
    except (TypeError, ValueError) as error:
        conflict = "idempotency conflict" in str(error)
        return ApiResponse(
            409 if conflict else 403,
            {"status": "force_stop_conflict" if conflict else "force_stop_denied"},
        )
    return ApiResponse(200 if read or result["state"] == "stopped" else 202, result)
