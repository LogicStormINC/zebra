"""Lock-free proof reads followed by exact native revalidation, never a proof cache."""

import json
import pickle
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from hashlib import sha256
from time import monotonic
from typing import Any, cast

from agent_storage.postgres.command_wakeup_recovery_proof import (
    CoverageRecoveryCheck,
    check_coverage_recovery_clock,
)

MAX_READS = 8192
MAX_TRANSCRIPT_BYTES = 32 * 1024 * 1024
MAX_FINALIZATION_AGE = timedelta(seconds=5)
_LOCK = re.compile(r"\s+FOR (?:UPDATE|SHARE)\s*$", re.IGNORECASE)


class CoverageRecoveryDeferred(RuntimeError):
    """Transient proof window exhaustion; rollback and prepare again, never ACK/dead."""


def remaining_recovery_time(deadline: float) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise CoverageRecoveryDeferred("prepared recovery deadline exhausted")
    return remaining


class RecoveryDeadlineConnection:
    """Carry one remaining budget through outer locks and exact native reads."""

    def __init__(self, connection: Any, deadline: float):
        self.connection, self.deadline = connection, deadline

    def __getattr__(self, name: str) -> Any:
        return getattr(self.connection, name)

    def __enter__(self) -> "RecoveryDeadlineConnection":
        self.connection.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> Any:
        if exc_type is None:
            try:
                remaining_recovery_time(self.deadline)
            except CoverageRecoveryDeferred as exhausted:
                self.connection.__exit__(type(exhausted), exhausted, exhausted.__traceback__)
                raise
        return self.connection.__exit__(exc_type, exc, traceback)

    def execute(self, sql: Any, params: Any = None) -> Any:
        from agent_storage.postgres.database import postgres_deadline

        # Delegation may cross an older owner wrapper through a work-unit borrow.
        # Every wrapper must install the minimum deadline, not its original one.
        with postgres_deadline(self.deadline) as deadline:
            milliseconds = str(max(1, int(remaining_recovery_time(deadline) * 1000)))
            self.connection.execute(
                "SELECT set_config('statement_timeout',%s,true),set_config('lock_timeout',%s,true)",
                (milliseconds, milliseconds),
            )
            remaining_recovery_time(deadline)
            try:
                cursor = self.connection.execute(sql, params)
            except Exception as exc:
                # Server-side cancellation is transient, never invalid certification.
                from psycopg.errors import LockNotAvailable, QueryCanceled

                if isinstance(exc, QueryCanceled | LockNotAvailable):
                    raise CoverageRecoveryDeferred("database proof deadline exhausted") from exc
                raise
            remaining_recovery_time(deadline)
            return _DeadlineCursor(cursor, deadline)


class _DeadlineCursor:
    def __init__(self, cursor: Any, deadline: float):
        self.cursor, self.deadline = cursor, deadline

    def __getattr__(self, name: str) -> Any:
        return getattr(self.cursor, name)

    def _read(self, method: str) -> Any:
        remaining_recovery_time(self.deadline)
        result = getattr(self.cursor, method)()
        remaining_recovery_time(self.deadline)
        return result

    def fetchone(self) -> Any:
        return self._read("fetchone")

    def fetchall(self) -> Any:
        return self._read("fetchall")


def prepared_recovery_connection(connection: Any, check: Any) -> Any:
    if not isinstance(check, PreparedCoverageRecovery):
        return connection
    check.check_clock(connection)
    now = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
    deadline = monotonic() + (check.prepared_at + MAX_FINALIZATION_AGE - now).total_seconds()
    return RecoveryDeadlineConnection(connection, deadline)


def _digest(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    return sha256(body).hexdigest()


def _read_digest(value: Any, method: str) -> str:
    # SQL sets may have no ORDER BY; preserve multiplicity and exact row contents.
    return (
        _digest(sorted(_digest(row) for row in value)) if method == "fetchall" else _digest(value)
    )


def _database_boundary(connection: Any) -> str:
    info = connection.info
    row = connection.execute(
        "SELECT d.oid AS database_oid,n.oid AS schema_oid,inet_server_addr() AS server_addr,"
        "inet_server_port() AS server_port FROM pg_database d "
        "JOIN pg_namespace n ON n.nspname=current_schema() WHERE d.datname=current_database()"
    ).fetchone()
    return _digest((info.host, info.port, info.dbname, row))


@dataclass(frozen=True)
class NativeRead:
    sql: str
    params: Any
    method: str
    digest: str


class _Cursor:
    def __init__(self, owner: "RecoveryReadSnapshot", sql: str, params: Any, cursor: Any):
        self.owner, self.sql, self.params, self.cursor = owner, sql, params, cursor

    def _read(self, method: str) -> Any:
        key = _digest((self.sql, self.params, method))
        cached = self.owner.cached_reads.get(key)
        if cached is not None:
            # Only bytes serialized by this same private RR preparation are loaded.
            result = pickle.loads(cached)
        else:
            cursor = self.cursor
            if cursor is None:
                cursor = self.owner.connection.execute(_LOCK.sub("", self.sql), self.params)
            result = getattr(cursor, method)()
        self.owner.record(NativeRead(self.sql, self.params, method, _read_digest(result, method)))
        if self.owner.reuse_reads and cached is None:
            body = pickle.dumps(result)
            if self.owner.cached_bytes + len(body) <= MAX_TRANSCRIPT_BYTES:
                self.owner.cached_reads[key] = body
                self.owner.cached_bytes += len(body)
        return result

    def fetchone(self) -> Any:
        return self._read("fetchone")

    def fetchall(self) -> Any:
        return self._read("fetchall")


class _NoLock:
    def fetchone(self) -> None:
        return None


@dataclass
class RecoveryReadSnapshot:
    """Restricted adapter over a REPEATABLE READ READ ONLY connection.

    Only trusted checker SELECTs are supported. Restore every original row lock
    during finalization; retain digests, not large query bodies. Unique SQL reads
    are bounded and deduplicated only when their complete results are identical.
    """

    connection: Any
    reads: dict[str, NativeRead] = field(default_factory=dict)
    size: int = 0
    database_boundary: str | None = None
    reuse_reads: bool = False
    cached_reads: dict[str, bytes] = field(default_factory=dict)
    cached_bytes: int = 0

    def bind_database(self) -> None:
        self.database_boundary = _database_boundary(self.connection)

    def execute(self, sql: str, params: Any = None) -> Any:
        if type(sql) is not str or not sql.lstrip().upper().startswith("SELECT "):
            raise ValueError("recovery preparation permits only native SELECT proof reads")
        if "pg_advisory_xact_lock" in sql:
            self.record(NativeRead(sql, params, "", ""))
            return _NoLock()
        if "clock_timestamp()" in sql:
            if sql.strip() != "SELECT clock_timestamp() AS now":
                raise ValueError("recovery preparation clock must be a standalone read")
            return self.connection.execute(sql, params)
        # ponytail: opt-in only after RR READ ONLY starts; cache at most 32 MiB.
        # Clock/authority reads outside this connection stay fresh; final replays SQL.
        cursor = None if self.reuse_reads else self.connection.execute(_LOCK.sub("", sql), params)
        return _Cursor(self, sql, params, cursor)

    def _bound(self, sql: str, params: Any) -> None:
        self.size += len(sql.encode()) + len(str(params).encode()) + 64
        if len(self.reads) >= MAX_READS or self.size > MAX_TRANSCRIPT_BYTES:
            raise ValueError("recovery preparation transcript exceeds its native bounds")

    def record(self, read: NativeRead) -> None:
        key = _digest((read.sql, read.params, read.method))
        previous = self.reads.get(key)
        if previous is not None:
            if previous != read:
                raise ValueError("recovery preparation read changed within its snapshot")
            return
        self._bound(read.sql, read.params)
        self.reads[key] = read

    def revalidate(self, connection: Any, deadline: float | None = None) -> None:
        if deadline is not None:
            if isinstance(connection, RecoveryDeadlineConnection):
                deadline = min(deadline, connection.deadline)
                connection = connection.connection
            connection = RecoveryDeadlineConnection(connection, deadline)
        if (
            self.database_boundary is not None
            and _database_boundary(connection) != self.database_boundary
        ):
            raise ValueError("prepared recovery database/schema boundary changed")
        # ponytail: O(unique native reads), not O(1) or an arbitrary-scale gate.
        # Lock order remains lease boundary -> Task/run -> payload lifecycle.
        for read in self.reads.values():
            if not read.method:
                connection.execute(read.sql, read.params)
                continue
            result = getattr(connection.execute(read.sql, read.params), read.method)()
            if _read_digest(result, read.method) != read.digest:
                raise ValueError("native recovery evidence changed after preparation")


@dataclass(frozen=True)
class PreparedCoverageRecovery:
    namespace: str
    pending_digest: str
    receipt_digest: str
    snapshot: RecoveryReadSnapshot
    proof: dict[str, Any]
    prepared_at: datetime
    final_authority: Callable[[float], None]

    def __call__(
        self, connection: Any, namespace: str, pending: Any, receipt: Any
    ) -> dict[str, Any]:
        if (
            namespace != self.namespace
            or _digest(pending) != self.pending_digest
            or _digest(receipt) != self.receipt_digest
        ):
            raise ValueError("prepared recovery command boundary changed")
        self.check_clock(connection)
        check_coverage_recovery_clock(connection, self.proof, pending=pending)
        now = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        deadline = monotonic() + (self.prepared_at + MAX_FINALIZATION_AGE - now).total_seconds()
        if isinstance(connection, RecoveryDeadlineConnection):
            deadline = min(deadline, connection.deadline)
        self.snapshot.revalidate(connection, deadline)
        remaining_recovery_time(deadline)
        try:
            self.final_authority(deadline)
        except ValueError:
            remaining_recovery_time(deadline)
            raise
        self.check_clock(connection)
        check_coverage_recovery_clock(connection, self.proof, pending=pending)
        return dict(self.proof)

    def check_clock(self, connection: Any) -> None:
        now = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        if not self.prepared_at <= now < self.prepared_at + MAX_FINALIZATION_AGE:
            raise CoverageRecoveryDeferred("prepared recovery exceeded its finalization window")


def check_prepared_recovery_clock(
    connection: Any,
    check: CoverageRecoveryCheck | None,
    *,
    proof: dict[str, Any] | None = None,
    pending: Any = None,
) -> None:
    if isinstance(check, PreparedCoverageRecovery):
        check.check_clock(connection)
    if proof is not None:
        check_coverage_recovery_clock(connection, proof, pending=pending)


def prepare_command_recovery(
    check: CoverageRecoveryCheck | None, namespace: str, event_id: Any,
    *, continuation: bool = False,
) -> CoverageRecoveryCheck | None:
    """Only explicitly composed native checkers opt in; legacy checks stay safe."""
    prepare = getattr(check, "prepare_continuation", None) if continuation else None
    if not callable(prepare):
        prepare = getattr(check, "prepare", None)
    if not callable(prepare):
        return check
    try:
        return cast(CoverageRecoveryCheck, prepare(namespace, event_id))
    except (ValueError, TypeError, KeyError):

        def refuse(connection: Any, ns: str, pending: Any, receipt: Any) -> dict[str, Any]:
            raise ValueError("native recovery preparation could not prove the checkpoint")

        return refuse


def prepare_command_handoff(
    check: CoverageRecoveryCheck | None, connection: Any, namespace: str,
    event_id: Any, generation: int,
) -> CoverageRecoveryCheck | None:
    """Select from native approval, then revalidate exact proof under pickup locks."""
    normal = None if generation == 0 else connection.execute(
        """SELECT a.reason,a.coverage_proof,r.wake_generation AS picked_generation
           FROM command_recovery_attempts a LEFT JOIN command_handoff_receipts r
             ON r.deployment_namespace=a.deployment_namespace
             AND r.accepted_event_id=a.accepted_event_id
           WHERE a.deployment_namespace=%s AND a.accepted_event_id=%s
             AND a.wake_generation=%s""",
        (namespace, event_id, generation),
    ).fetchone()
    protocol = normal["coverage_proof"].get("continuation_protocol") if (
        normal is not None and isinstance(normal["coverage_proof"], dict)
    ) else None
    if protocol is not None and (
        protocol != "coverage-execution-receipt/1"
        or normal is None or normal["reason"] != "coverage_continuation"
        or not callable(getattr(check, "prepare_continuation", None))
    ):
        raise ValueError("command requires a supported native continuation consumer")
    # Pickup only: approval creation must still prove the current producing generation.
    # The locked handoff rechecks generation and identity before returning no lease.
    if protocol is not None and normal is not None and normal["picked_generation"] == generation:
        return check
    return prepare_command_recovery(check, namespace, event_id, continuation=protocol is not None)
