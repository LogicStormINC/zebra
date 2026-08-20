"""Reconcile replayed creates whose run command never landed."""

from __future__ import annotations

from typing import Any

from zebra_agent_api.responses import ApiResponse


def reconcile_replayed_run(
    app: Any,
    replayed: ApiResponse,
    payload: dict[str, object],
    idempotency_key: str | None,
) -> ApiResponse:
    """Re-submit the run command when a replay's original never landed.

    Admission, run-command submission and the receipt-body update are
    separate writes; a crash between them leaves a durable Session with
    no queued execution. On replay, an execute request whose stored body
    carries no run command re-submits it under the same command
    idempotency key (safe against duplicates) and syncs the stored body,
    so the retried request also re-queues execution.
    """

    settings = app.settings
    if (
        replayed.status_code != 201
        or payload.get("execute") is not True
        or getattr(settings, "deployment", "") != "cloud"
        or replayed.body.get("command") is not None
        or idempotency_key is None
    ):
        return replayed

    session_id = replayed.body.get("session_id")
    if not isinstance(session_id, str):
        return replayed
    session_key = app._parse_session_id(session_id)
    if isinstance(session_key, ApiResponse):
        return replayed
    from uuid import UUID

    from agent_core.domain.identifiers import SessionId

    if app.stores.sessions.get_session(SessionId(UUID(session_id))) is None:
        return replayed
    reconciled = app.queue_cloud_run(replayed, idempotency_key=idempotency_key)
    if reconciled is replayed or not isinstance(reconciled, ApiResponse):
        return replayed
    if reconciled.status_code != 201:
        return replayed
    if getattr(settings, "storage_authority", "") == "postgresql":
        from agent_storage.postgres.task_admission import (
            update_idempotency_response,
        )

        update_idempotency_response(
            getattr(settings, "database_url", ""),
            deployment_namespace=str(
                getattr(app.stores, "deployment_namespace", "zebra")
            ),
            action="session.create",
            idempotency_key=idempotency_key,
            response_body=reconciled.body,
        )
    return reconciled
