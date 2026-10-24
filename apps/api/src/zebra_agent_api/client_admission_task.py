"""Prepare bounded Task admission before locks; reuse the existing atomic bootstrap."""

from collections.abc import Callable
from typing import Any

from agent_storage import PostgresControlPlaneStores

from zebra_agent_api.agent_definition_binding import resolve_definition_binding
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_binding import _compose_admission
from zebra_agent_api.session_payloads import parse_create_session_payload
from zebra_agent_api.session_queue import create_queued_session


def validate_atomic_task(app: Any, body: Any) -> None:
    # ponytail: explicit narrow protocol; attachments/MCP/workspace allocation and
    # executing Coverage require separate external-effect protocols, never rollback claims.
    if (
        body.kind != "task_create"
        or body.task
        or body.run
        or body.payload.get("execute") is not False
    ):
        raise ValueError("atomic Task requires non-executing root creation")
    if (
        any(
            body.payload.get(k)
            for k in (
                "attachments",
                "workspace_source",
                "mcp_resource_ids",
                "mcp_prompt_id",
                "mcp_prompt_arguments",
                "mcp_allowlist",
                "coverage_admission",
            )
        )
        or "coverage_admission" in body.payload
    ):
        raise ValueError("external or executing effects unsupported")
    if type(app.stores) is not PostgresControlPlaneStores:
        raise ValueError("native PG stores required")
    db = getattr(app.stores.idempotency, "_database", None)
    if db is None:
        raise ValueError("native idempotency database required")
    if (
        app.settings.storage_authority,
        app.settings.deployment,
        app.settings.database_url,
        app.stores.deployment_namespace,
    ) != ("postgresql", "cloud", db._dsn, db.deployment_namespace):
        raise ValueError("atomic Task database differs")


def prepare_atomic_task(
    app: Any, request: Any, body: Any, scoped: str
) -> Callable[[], ApiResponse] | None:
    validate_atomic_task(app, body)
    parsed = parse_create_session_payload(body.payload)
    if isinstance(parsed, ApiResponse):
        return None
    # Definition resolution and possible Host manifest discovery happen BEFORE
    # the execution row lock; committed manifest/audit facts are outside noncommit.
    snapshot = resolve_definition_binding(
        app.agent_registry,
        app.publisher_grants,
        parsed,
        host_context=request.host_context,
        settings=app.settings,
        verified_host_grant=request.verified_host_grant,
    )
    if isinstance(snapshot, ApiResponse):
        return None
    original_key = "admission-v1:" + scoped
    from zebra_agent_api.idempotency import scoped_idempotency_key

    storage_key = scoped_idempotency_key(original_key, request.host_context)
    kwargs = _compose_admission(app, request.host_context, body.payload, storage_key)
    if isinstance(kwargs, ApiResponse):
        return None
    if not isinstance(kwargs, dict):
        raise ValueError("atomic Task composition unavailable")

    def admit() -> ApiResponse:
        response = create_queued_session(
            app.stores,
            parsed,
            host_context=request.host_context,
            definition_snapshot=snapshot,
            verified_host_grant=request.verified_host_grant,
            **kwargs,
        )
        if response.status_code == 201:
            # Atomic root admission already creates the Task index; the root Task
            # and active segment share the Session UUID and bootstrap sequence.
            response.body.update(
                task_id=response.body["session_id"],
                active_segment_sequence=response.body["current_sequence"],
                idempotency_key=original_key,
            )
        return response

    return admit
