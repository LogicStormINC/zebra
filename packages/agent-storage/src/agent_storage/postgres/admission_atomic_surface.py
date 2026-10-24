"""Atomic PG-only surface effects/result and cooperative commit fencing. No takeover."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from psycopg.errors import LockNotAvailable

from agent_storage.idempotency import IdempotencyConflictError, new_idempotency_record
from agent_storage.postgres.admission_dispatch_fence import CLAIM, FENCE
from agent_storage.postgres.work_unit import postgres_transaction_work_unit

PROTOCOL = "atomic-surface/1"
STOP = "client-admission-v1-atomic-stop"
RESULT = "client-admission-v1-result"


class AtomicSurfaceAborted(Exception):
    """The entire effect/result transaction must roll back, never seal partial failure."""


def _claim(store: Any, connection: Any, scoped: str, digest: str, *, nowait: bool = False) -> Any:
    row = connection.execute(
        """SELECT request_hash,response_body FROM control_plane_idempotency_records
        WHERE deployment_namespace=%s AND action=%s AND idempotency_key=%s FOR UPDATE"""
        + (" NOWAIT" if nowait else ""),
        (store._database.deployment_namespace, CLAIM, scoped),
    ).fetchone()
    if row is not None and row["request_hash"] != digest:
        raise IdempotencyConflictError("atomic original differs")
    return row


def _save(store: Any, connection: Any, action: str, scoped: str, digest: str, state: str) -> Any:
    from dataclasses import replace

    return store.save(
        replace(
            new_idempotency_record(
                action=action,
                idempotency_key=scoped,
                request_hash=digest,
                status_code=200,
                response_body={"state": state},
            ),
            created_at=connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"],
        )
    )


def start_atomic_surface(store: Any, scoped: str, digest: str) -> bool:
    database = store._database
    with database.connect() as connection, postgres_transaction_work_unit(database, connection):
        connection.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        claim = _claim(store, connection, scoped, digest)
        if claim is None or claim["response_body"].get("dispatch_protocol") != PROTOCOL:
            raise AtomicSurfaceAborted("atomic protocol missing")
        if store.get(action=STOP, idempotency_key=scoped) is not None:
            return False
        record = _save(store, connection, FENCE, scoped, digest, "started")
        return bool(record.request_hash == digest and record.response_body["state"] == "started")


@contextmanager
def atomic_surface_transaction(store: Any, scoped: str, digest: str) -> Iterator[None]:
    database = store._database
    with database.connect() as connection, postgres_transaction_work_unit(database, connection):
        connection.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        fence = connection.execute(
            """SELECT request_hash FROM control_plane_idempotency_records
            WHERE deployment_namespace=%s AND action=%s AND idempotency_key=%s FOR UPDATE""",
            (database.deployment_namespace, FENCE, scoped),
        ).fetchone()
        if fence is None or fence["request_hash"] != digest:
            raise AtomicSurfaceAborted("execution fence missing")
        if store.get(action=STOP, idempotency_key=scoped) is not None:
            raise AtomicSurfaceAborted("original stopped")
        # Only exact same-PG local surface adapters are composed by the API.
        # This row lock lives at most the existing two-second request budget.
        yield
        _claim(store, connection, scoped, digest)
        if store.get(action=STOP, idempotency_key=scoped) is not None:
            raise AtomicSurfaceAborted("stop won the commit fence")


def observe_atomic_termination(
    store: Any, scoped: str, digest: str, *, write: bool
) -> dict[str, str]:
    database = store._database
    if write:
        with database.connect() as connection, postgres_transaction_work_unit(database, connection):
            connection.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            claim = _claim(store, connection, scoped, digest)
            if claim is None:
                return {"state": "not_observed", "recorded_at": ""}
            if claim["response_body"].get("dispatch_protocol") != PROTOCOL:
                return {"state": "unsupported", "recorded_at": ""}
            # Durable stop first; a successful commit holding the same claim row wins first.
            if store.get(action=RESULT, idempotency_key=scoped) is None:
                _save(store, connection, STOP, scoped, digest, "stop_requested")
    try:
        with database.connect() as connection, postgres_transaction_work_unit(database, connection):
            connection.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            # Match execution->claim lock order. NOWAIT never waits for active execution.
            connection.execute(
                """SELECT request_hash FROM control_plane_idempotency_records
                WHERE deployment_namespace=%s AND action=%s AND idempotency_key=%s
                FOR UPDATE NOWAIT""",
                (database.deployment_namespace, FENCE, scoped),
            ).fetchone()
            claim = _claim(store, connection, scoped, digest, nowait=True)
            if claim is None:
                return {"state": "not_observed", "recorded_at": ""}
            if claim["response_body"].get("dispatch_protocol") != PROTOCOL:
                return {"state": "unsupported", "recorded_at": ""}
            result = store.get(action=RESULT, idempotency_key=scoped)
            if result is not None:
                if result.request_hash != digest:
                    raise IdempotencyConflictError("atomic receipt differs")
                return {"state": "committed", "recorded_at": result.created_at.isoformat()}
            stop = store.get(action=STOP, idempotency_key=scoped)
            if stop is None:
                return {"state": "unresolved", "recorded_at": ""}
            if stop.request_hash != digest:
                raise IdempotencyConflictError("atomic stop differs")
            # Execution lock is free, stop is durable, and all effects share the absent
            # result's transaction. A late original must check this stop before commit.
            return {"state": "terminated", "recorded_at": stop.created_at.isoformat()}
    except LockNotAvailable:
        return {"state": "pending", "recorded_at": ""}
