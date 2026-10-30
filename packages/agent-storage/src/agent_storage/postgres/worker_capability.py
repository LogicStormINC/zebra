"""DB-clock process leases; publication belongs to the actual consumer loop.

No method here activates admission. Restored databases must rotate their existing
control-plane epoch before enabling writers, just as with Session lease fencing.
"""

import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.worker_capability_configuration import (
    STRICT_WORKER_CONTRACT as STRICT_WORKER_CONTRACT,
)
from agent_storage.worker_capability_configuration import continuation_configuration_digest


@dataclass(frozen=True)
class WorkerCapabilityLease:
    process_id: UUID
    epoch: UUID
    sequence: int
    expires_at: datetime
    # Observational reads deliberately cannot reconstruct process attestation.
    attestation: str | None = field(default=None, repr=False, compare=False)
    local_pid: int | None = field(default=None, repr=False, compare=False)


class WorkerCapabilityLostError(RuntimeError):
    """Expired, revoked, replaced or replayed process authority cannot renew."""


class WorkerCapabilityExpiredError(WorkerCapabilityLostError):
    """Only a valid, unrevoked registration naturally expired; never resurrect it."""


def validate_capability_inputs(configuration_digest: str, ttl_seconds: int) -> None:
    if (
        type(configuration_digest) is not str
        or re.fullmatch(r"[0-9a-f]{64}", configuration_digest) is None
    ):
        raise ValueError("worker configuration digest must be canonical SHA256")
    if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 30:
        raise ValueError("worker process lease TTL must be an integer within 1..30")


class PostgresWorkerCapabilities:
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    def _connect(self) -> Connection[dict[str, Any]]:
        # Native identity is resolved on this connection, not from a DSN hash.
        return psycopg.connect(self._database._dsn, connect_timeout=2, row_factory=dict_row)

    def register(
        self,
        process_id: UUID,
        *,
        configuration_digest: str,
        ttl_seconds: int = 30,
        expired_lease: WorkerCapabilityLease | None = None,
        continuation_digest: str | None = None,
    ) -> WorkerCapabilityLease:
        validate_capability_inputs(configuration_digest, ttl_seconds)
        _validate_continuation(configuration_digest, continuation_digest)
        if type(process_id) is not UUID:
            raise ValueError("worker process identity must be a UUID")
        attestation = secrets.token_hex(32)
        with self._connect() as connection:
            _require_schema(connection)
            # Share-lock the epoch across publication; rotation invalidates every reader.
            authority = connection.execute(
                "SELECT epoch FROM control_plane_epochs WHERE deployment_namespace=%s FOR SHARE",
                (self._database.deployment_namespace,),
            ).fetchone()
            if authority is None:
                raise WorkerCapabilityLostError("worker epoch authority is unavailable")
            if expired_lease is not None:
                if (
                    authority["epoch"] != expired_lease.epoch
                    or process_id == expired_lease.process_id
                ):
                    raise WorkerCapabilityLostError(
                        "expired registration replacement epoch changed"
                    )
                previous, now = _locked_registration(
                    connection,
                    self._database.deployment_namespace,
                    expired_lease,
                    configuration_digest,
                    continuation_digest,
                )
                if previous["expires_at"] > now:
                    raise WorkerCapabilityLostError("replacement requires natural expiry")
                connection.execute(
                    "UPDATE worker_process_capabilities SET revoked_at=%s "
                    "WHERE deployment_namespace=%s AND process_id=%s",
                    (now, self._database.deployment_namespace, expired_lease.process_id),
                )
            row = connection.execute(
                """WITH stamp AS (SELECT clock_timestamp() AS now)
                INSERT INTO worker_process_capabilities
                  (deployment_namespace,process_id,epoch,database_name,schema_name,
                   schema_oid,contract,configuration_digest,sequence,registered_at,
                   heartbeat_at,expires_at,attestation_digest,continuation_digest)
                SELECT %s,%s,%s,current_database(),current_schema(),
                  current_schema()::regnamespace::oid,%s,%s,1,now,now,
                  now + %s * interval '1 second',%s,%s FROM stamp
                ON CONFLICT DO NOTHING RETURNING process_id,epoch,sequence,expires_at""",
                (
                    self._database.deployment_namespace,
                    process_id,
                    authority["epoch"],
                    STRICT_WORKER_CONTRACT,
                    configuration_digest,
                    ttl_seconds,
                    sha256(attestation.encode()).hexdigest(),
                    continuation_digest,
                ),
            ).fetchone()
        if row is None:
            raise WorkerCapabilityLostError("worker process identity cannot be reused")
        return WorkerCapabilityLease(**row, attestation=attestation, local_pid=os.getpid())

    def heartbeat(
        self, lease: WorkerCapabilityLease, *, configuration_digest: str, ttl_seconds: int = 30,
        continuation_digest: str | None = None,
    ) -> WorkerCapabilityLease:
        validate_capability_inputs(configuration_digest, ttl_seconds)
        _validate_continuation(configuration_digest, continuation_digest)
        with self._connect() as connection:
            _require_schema(connection)
            authority = connection.execute(
                "SELECT epoch FROM control_plane_epochs WHERE deployment_namespace=%s FOR SHARE",
                (self._database.deployment_namespace,),
            ).fetchone()
            if authority is None or authority["epoch"] != lease.epoch:
                raise WorkerCapabilityLostError("worker epoch authority changed")
            # Take the row lock BEFORE reading the clock. A waiting renewal must
            # not revive authority that expired while blocked by another writer.
            previous, now = _locked_registration(
                connection,
                self._database.deployment_namespace,
                lease,
                configuration_digest,
                continuation_digest,
            )
            if previous["expires_at"] <= now:
                raise WorkerCapabilityExpiredError("worker process capability naturally expired")
            row = connection.execute(
                """UPDATE worker_process_capabilities c
                SET sequence=c.sequence+1,heartbeat_at=%s,expires_at=%s
                WHERE deployment_namespace=%s AND process_id=%s
                  AND epoch=%s AND sequence=%s AND configuration_digest=%s
                  AND contract=%s AND revoked_at IS NULL
                  AND database_name=current_database() AND schema_name=current_schema()
                  AND schema_oid=current_schema()::regnamespace::oid
                RETURNING process_id,epoch,sequence,expires_at""",
                (
                    now,
                    now + timedelta(seconds=ttl_seconds),
                    self._database.deployment_namespace,
                    lease.process_id,
                    lease.epoch,
                    lease.sequence,
                    configuration_digest,
                    STRICT_WORKER_CONTRACT,
                ),
            ).fetchone()
        if row is None:
            raise WorkerCapabilityLostError("worker process capability is no longer current")
        return WorkerCapabilityLease(
            **row,
            attestation=lease.attestation,
            local_pid=lease.local_pid,
        )

    def revoke(self, lease: WorkerCapabilityLease) -> None:
        with self._connect() as connection:
            connection.execute("SET LOCAL statement_timeout = '2s'")
            connection.execute(
                """UPDATE worker_process_capabilities SET revoked_at=clock_timestamp()
                WHERE deployment_namespace=%s AND process_id=%s AND epoch=%s
                  AND revoked_at IS NULL""",
                (self._database.deployment_namespace, lease.process_id, lease.epoch),
            )

    def current(self, *, configuration_digest: str) -> tuple[WorkerCapabilityLease, ...]:
        """Observational only: not an admission transaction or a routing fence."""
        validate_capability_inputs(configuration_digest, 30)
        with self._connect() as connection:
            _require_schema(connection)
            rows = connection.execute(
                """SELECT c.process_id,c.epoch,c.sequence,c.expires_at
                FROM worker_process_capabilities c JOIN control_plane_epochs e
                  USING (deployment_namespace,epoch)
                WHERE deployment_namespace=%s AND contract=%s AND configuration_digest=%s
                  AND revoked_at IS NULL AND expires_at>clock_timestamp()
                  AND attestation_digest IS NOT NULL
                  AND database_name=current_database() AND schema_name=current_schema()
                  AND schema_oid=current_schema()::regnamespace::oid
                ORDER BY process_id LIMIT 65""",
                (self._database.deployment_namespace, STRICT_WORKER_CONTRACT, configuration_digest),
            ).fetchall()
        if len(rows) > 64:
            raise WorkerCapabilityLostError("worker process capability lookup exceeds bound")
        return tuple(WorkerCapabilityLease(**row) for row in rows)


def _require_schema(connection: Connection[dict[str, Any]]) -> None:
    from agent_storage.postgres.migration_history_plan import migration_history_plan

    connection.execute("SET LOCAL lock_timeout = '2s'")
    connection.execute("SET LOCAL statement_timeout = '2s'")
    applied = {
        row["version"]: (row["name"], row["checksum"])
        for row in connection.execute(
            "SELECT version,name,checksum FROM zebra_schema_migrations"
        ).fetchall()
    }
    plan = migration_history_plan(applied)
    if len(applied) != len(plan) or any(
        applied.get(m.version) != (m.name, m.checksum) for m in plan
    ):
        raise WorkerCapabilityLostError("worker capability requires the verified schema")


def _validate_continuation(digest: str, qualification: str | None) -> None:
    if qualification is not None and qualification != continuation_configuration_digest(digest):
        raise ValueError("continuation qualification does not match native configuration")


def _locked_registration(
    connection: Any,
    namespace: str,
    lease: WorkerCapabilityLease,
    digest: str,
    continuation_digest: str | None = None,
) -> tuple[Any, datetime]:
    previous = connection.execute(
        """SELECT *, (database_name=current_database() AND schema_name=current_schema()
          AND schema_oid=current_schema()::regnamespace::oid) AS native_identity
        FROM worker_process_capabilities WHERE deployment_namespace=%s AND process_id=%s
        FOR UPDATE""",
        (namespace, lease.process_id),
    ).fetchone()
    if (
        previous is None
        or previous["epoch"] != lease.epoch
        or previous["sequence"] != lease.sequence
        or previous["revoked_at"] is not None
        or previous["contract"] != STRICT_WORKER_CONTRACT
        or previous["configuration_digest"] != digest
        or previous["continuation_digest"] != continuation_digest
        or not previous["native_identity"]
        or lease.local_pid != os.getpid()
        or not isinstance(lease.attestation, str)
        or previous["attestation_digest"] != sha256(lease.attestation.encode()).hexdigest()
    ):
        raise WorkerCapabilityLostError("worker registration is revoked, changed or replayed")
    stamp = connection.execute("SELECT clock_timestamp() AS now").fetchone()
    if stamp is None:
        raise WorkerCapabilityLostError("worker registration clock unavailable")
    return previous, stamp["now"]


def pin_worker_capability(
    connection: Any,
    namespace: str,
    *,
    contract: str,
    configuration_digest: str,
    consumer_capability: WorkerCapabilityLease | None = None,
    require_process: bool = False,
    continuation_digest: str | None = None,
) -> WorkerCapabilityLease:
    """Caller transaction: epoch SHARE then capability SHARE, never another DB."""
    validate_capability_inputs(configuration_digest, 30)
    _validate_continuation(configuration_digest, continuation_digest)
    if contract != STRICT_WORKER_CONTRACT:
        raise WorkerCapabilityLostError("unsupported strict Worker contract")
    if require_process and (
        type(consumer_capability) is not WorkerCapabilityLease
        or consumer_capability.local_pid != os.getpid()
        or not isinstance(consumer_capability.attestation, str)
        or re.fullmatch(r"[0-9a-f]{64}", consumer_capability.attestation) is None
    ):
        raise WorkerCapabilityLostError("same-process Worker attestation is required")
    _require_schema(connection)
    authority = connection.execute(
        "SELECT epoch FROM control_plane_epochs WHERE deployment_namespace=%s FOR SHARE",
        (namespace,),
    ).fetchone()
    if authority is None:
        raise WorkerCapabilityLostError("worker epoch authority is unavailable")
    process = consumer_capability if require_process else None
    row = connection.execute(
        """SELECT process_id,epoch,sequence,expires_at FROM worker_process_capabilities
        WHERE deployment_namespace=%s AND epoch=%s AND contract=%s
          AND configuration_digest=%s AND revoked_at IS NULL AND attestation_digest IS NOT NULL
          AND expires_at>clock_timestamp() AND database_name=current_database()
          AND schema_name=current_schema() AND schema_oid=current_schema()::regnamespace::oid
          AND (%s::text IS NULL OR continuation_digest=%s)
          AND (%s::uuid IS NULL OR (process_id=%s AND epoch=%s AND sequence>=%s
               AND attestation_digest=%s))
        ORDER BY process_id LIMIT 1 FOR SHARE""",
        (
            namespace,
            authority["epoch"],
            contract,
            configuration_digest,
            continuation_digest,
            continuation_digest,
            None if process is None else process.process_id,
            None if process is None else process.process_id,
            None if process is None else process.epoch,
            None if process is None else process.sequence,
            None if process is None else sha256(str(process.attestation).encode()).hexdigest(),
        ),
    ).fetchone()
    if row is None:
        raise WorkerCapabilityLostError("live matching Worker capability is unavailable")
    lease = WorkerCapabilityLease(**row)
    check_worker_capability_clock(connection, lease)
    return lease


def check_worker_capability_clock(connection: Any, lease: WorkerCapabilityLease) -> None:
    """Invoke again after all writes and lock waits, immediately before commit."""
    stamp = connection.execute("SELECT clock_timestamp() AS now").fetchone()
    if stamp is None or lease.expires_at <= stamp["now"]:
        raise WorkerCapabilityLostError("worker process capability expired before commit")
