"""Explicit same-PG surface composition; legacy admissions retain their old commits."""

import logging
from time import monotonic
from traceback import walk_tb
from typing import Any

from agent_core.ports.idempotency_store import IdempotencyRecord
from agent_storage.postgres.admission_atomic_surface import (
    AtomicSurfaceAborted,
    atomic_surface_transaction,
    start_atomic_surface,
)
from agent_storage.postgres.client_capabilities import PostgresClientCapabilityRegistry
from agent_storage.postgres.client_control_leases import PostgresClientControlLeaseStore
from agent_storage.postgres.client_sessions import PostgresClientSessionRegistry
from agent_storage.postgres.task_io import current_task_io_deadline
from psycopg.errors import LockNotAvailable

logger = logging.getLogger(__name__)


def eligible_atomic_surface(app: Any) -> bool:
    platform = app.client_platform
    if platform is None:
        return False
    database = app.stores.idempotency._database
    for port, expected in (
        (platform.client_sessions, PostgresClientSessionRegistry),
        (platform.client_control_leases, PostgresClientControlLeaseStore),
        (platform.frontend_capabilities, PostgresClientCapabilityRegistry),
    ):
        if type(port) is not expected:
            return False
        if (port._database._dsn, port._database.deployment_namespace) != (
            database._dsn,
            database.deployment_namespace,
        ):
            return False
    return True


def execute_atomic_surface(
    app: Any, request: Any, body: Any, scoped: str, key: bytes, digest: str, operation: str,
    *, original_claim: dict[str, Any] | None = None,
) -> IdempotencyRecord | None:
    from zebra_agent_api.client_admission_operations import _authorize, _dispatch, _persist_result

    started = monotonic()
    store = app.stores.idempotency
    protocol = "atomic-task/1" if body.kind == "task_create" else "atomic-surface/1"
    from zebra_agent_api.client_admission_operations import _header

    if _header(request, "X-Zebra-Admission-Protocol") == "atomic-task-run/1":
        protocol = "atomic-task-run/1"
    if _header(request, "X-Zebra-Admission-Protocol") == "atomic-task-run-surface/1":
        protocol = "atomic-task-run-surface/1"
    if _header(request, "X-Zebra-Admission-Protocol") == "atomic-message-surface/1":
        protocol = "atomic-message-surface/1"
    prepared = None
    if protocol in {"atomic-task/1", "atomic-task-run/1"}:
        from zebra_agent_api.client_admission_task import prepare_atomic_task

        prepared = prepare_atomic_task(
            app, request, body, scoped, initial_run=protocol == "atomic-task-run/1"
        )
        if prepared is None:
            return None
    if protocol == "atomic-task-run-surface/1":
        from zebra_agent_api.client_admission_task_surface import prepare_initial_surface

        prepared = prepare_initial_surface(app, request, body, scoped)
        if prepared is None:
            return None
    prepared_at = monotonic()
    if not start_atomic_surface(store, scoped, digest, protocol=protocol):
        return None
    fenced_at = monotonic()
    stages: list[tuple[str, int]] = []

    def mark(stage: str) -> None:
        if protocol == "atomic-task-run/1":
            stages.append((stage, int((monotonic() - started) * 1000)))

    def dispatch_transaction() -> IdempotencyRecord:
        mark("transaction_begin")
        with atomic_surface_transaction(store, scoped, digest):
            mark("transaction_entered")
            rejected = False
            if protocol == "atomic-message-surface/1":
                from agent_storage.postgres.message_surface_anchor import lock_message_anchor

                reason = lock_message_anchor(
                    store, task=body.task, run_id=body.run, **body.original_message.model_dump()
                )
                if reason is not None:
                    from zebra_agent_api.responses import ApiResponse

                    rejected = True
                    response = ApiResponse(
                        409,
                        {
                            "status": "message_anchor_conflict",
                            "reason": reason,
                            "retry_allowed": False,
                            "controller_reclaim_allowed": False,
                            "non_commit_proven": False,
                        },
                    )
            if not rejected:
                response = (
                    prepared() if prepared is not None else _dispatch(app, request, body, scoped)
                )
                if protocol == "atomic-message-surface/1" and response.status_code == 201:
                    from agent_storage.postgres.message_surface_anchor import consume_message_anchor

                    from zebra_agent_api.responses import ApiResponse

                    consume_message_anchor(
                        store,
                        task=body.task,
                        event_id=body.original_message.event_id,
                        scoped=scoped,
                        digest=digest,
                        run=body.run,
                    )
                    response = ApiResponse(
                        201,
                        {**response.body, "original_message": body.original_message.model_dump()},
                    )
            # Any partial error, budget/receipt failure or final denial rolls back every
            # surface write. No external I/O/Worker execution is admitted by this protocol.
            mark("dispatch_finished")
            meta = original_claim
            if meta is None:
                meta = store.get(
                    action="client-admission-v1-claim", idempotency_key=scoped
                ).response_body
            if (response.status_code != 201 and not rejected) or _authorize(
                app, request, meta
            ) is not None:
                raise AtomicSurfaceAborted("surface not admitted")
            result = _persist_result(store, response, operation, scoped, key, digest)
            if result is None:
                raise AtomicSurfaceAborted("atomic receipt unavailable")
            mark("receipt_written")
        mark("transaction_committed")
        return result

    failure: Exception | None = None
    try:
        try:
            return dispatch_transaction()
        except LockNotAvailable:
            deadline = current_task_io_deadline()
            if protocol != "atomic-task-run/1" or deadline is None or monotonic() >= deadline:
                raise
            # The first transaction rolled back. Reenter the original fence so
            # a concurrent termination still wins before any admission write.
            return dispatch_transaction()
    except AtomicSurfaceAborted as exc:
        failure = exc
        return None
    except Exception as exc:
        failure = exc
        raise
    finally:
        if stages:
            log = logger.info if stages[-1][0] == "transaction_committed" else logger.warning
            frames = [
                (frame.f_code.co_name, line)
                for frame, line in walk_tb(failure.__traceback__)
            ][-12:] if failure is not None else []
            log(
                "Atomic first Run milestones operation_id=%s error_type=%s frames=%s elapsed_ms=%s",
                operation,
                type(failure).__name__ if failure is not None else None,
                frames,
                [
                    ("prepared", int((prepared_at - started) * 1000)),
                    ("fenced", int((fenced_at - started) * 1000)),
                    *stages,
                    ("dispatch_return", int((monotonic() - started) * 1000)),
                ],
            )
