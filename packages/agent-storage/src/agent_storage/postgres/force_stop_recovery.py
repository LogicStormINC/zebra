"""Out-of-harness stop advancement: fenced revocation and bounded canonical repair."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from time import monotonic
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import SessionId
from agent_core.domain.task_bindings import require_task_host_context
from psycopg.rows import dict_row

from agent_storage.postgres.command_read_state import finish_command_read_state
from agent_storage.postgres.command_runtime_cleanup import CleanupTarget, _target
from agent_storage.postgres.connection_capacity import connect
from agent_storage.postgres.database import PostgresDatabase, postgres_deadline
from agent_storage.postgres.force_stop_executors import executors_exited
from agent_storage.postgres.force_stop_signal import STOP_REASON, stop_requested
from agent_storage.postgres.force_stop_targets import stop_targets
from agent_storage.postgres.leases import _lock_epoch, _lock_lease_and_clock
from agent_storage.postgres.projections import save_session_in_transaction
from agent_storage.postgres.session_cancellation import (
    cancel_in_transaction,
    lock_cancellation_context,
)
from agent_storage.postgres.workspaces import save_workspace_in_transaction


class PostgresForceStopRecovery:
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self.database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self.namespace = deployment_namespace

    def pending(self, limit: int = 4, *, engine_identity: str | None = None) -> list[UUID]:
        if engine_identity is not None and (
            len(engine_identity) != 64 or any(c not in "0123456789abcdef" for c in engine_identity)
        ):
            raise ValueError("invalid cleanup engine identity")
        # Leave foreign-only frontiers to their owner; empty/unremembered frontiers
        # still get lease revocation and canonical synchronization on any cleaner.
        affinity = """
            AND ((CASE WHEN reason='user_force_stop' THEN diagnostics::jsonb END
                    ->>'lease') IS DISTINCT FROM 'revoked'
              OR (CASE WHEN reason='user_force_stop' THEN diagnostics::jsonb END
                    ->>'synchronization') IS DISTINCT FROM 'synchronized'
              OR (CASE WHEN reason='user_force_stop' THEN diagnostics::jsonb END
                    ->>'error_code')='stop_frontier_advanced'
              OR (CASE WHEN reason='user_force_stop' THEN diagnostics::jsonb END
                    ->>'accepted_at')::timestamptz<clock_timestamp()-interval '10 minutes'
              OR NOT EXISTS (
                SELECT 1 FROM runtime_instances i
                WHERE i.deployment_namespace=agent_safety_overrides.deployment_namespace
                AND i.status<>'removed'
                AND (CASE WHEN reason='user_force_stop' THEN diagnostics::jsonb END)
                    ->'target_sessions' ? i.session_id::text
                HAVING bool_and(i.engine_identity IS DISTINCT FROM %s)
            ))"""
        # ponytail: rare emergency stops share the safety channel. At fleet stop
        # volume, add a partial pending-phase index instead of retaining scan cost.
        with self.database.connect_task_io() as connection:
            rows = connection.execute(
                f"""SELECT session_id FROM agent_safety_overrides
                WHERE deployment_namespace=%s AND reason=%s AND NOT shadow AND kind='watchdog'
                AND (CASE WHEN reason='user_force_stop' THEN diagnostics::jsonb END)->>'phase'
                    IN ('requested','stopping')
                AND COALESCE((CASE WHEN reason='user_force_stop' THEN diagnostics::jsonb
                    END->>'next_attempt_at')::timestamptz,created_at)
                    <=clock_timestamp() {affinity} ORDER BY created_at,session_id LIMIT %s""",
                (self.namespace, STOP_REASON, engine_identity, limit),
            ).fetchall()
        return [r["session_id"] for r in rows]

    @contextmanager
    def claim(self, sid: UUID) -> Iterator[dict[str, Any] | None]:
        # Session-level advisory lock on a PRIVATE autocommit connection: no open
        # transaction during engine I/O, auto-release on process/connection loss.
        with connect(
            self.database._dsn, budget=self.database._capacity, lane="control",
            autocommit=True, row_factory=dict_row, connect_timeout=3
        ) as connection:
            connection.execute("SET statement_timeout='1500ms'")
            key = f"force-recovery:{self.namespace}:{sid}"
            acquired_row = connection.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS acquired",
                (key,),
            ).fetchone()
            acquired = acquired_row is not None and acquired_row["acquired"]
            if not acquired:
                yield None
                return
            try:
                row = connection.execute(
                    """SELECT diagnostics FROM agent_safety_overrides WHERE deployment_namespace=%s
                    AND session_id=%s AND reason=%s AND kind='watchdog' AND NOT shadow""",
                    (self.namespace, sid, STOP_REASON),
                ).fetchone()
                data = None if row is None else json.loads(row["diagnostics"])
                yield data if data and data["phase"] in {"requested", "stopping"} else None
            finally:
                connection.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (key,))

    def targets(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        targets = stop_targets(self.database, data)
        root = next(t["binding"] for t in targets if str(t["binding"].task_id) == data["task_id"])
        require_task_host_context(
            root,
            HostContextEnvelope.model_validate(data["context"]),
            task_id=data["task_id"],
            now=datetime.fromisoformat(data["accepted_at"]),
            authority_issuer=data["authority_issuer"],
        )
        expected = sha256(f"force-stop:{data['task_id']}".encode()).hexdigest()
        with self.database.connect_task_io() as connection:
            row = connection.execute(
                """SELECT 1 FROM control_plane_idempotency_records WHERE deployment_namespace=%s
                AND action='force_stop' AND request_hash=%s
                AND response_body->>'stop_id'=%s LIMIT 1""",
                (self.namespace, expected, data["operation_id"]),
            ).fetchone()
            if row is None:
                raise ValueError("stop_admission_unproven")
        return targets

    def remember(self, data: dict[str, Any], targets: list[dict[str, Any]]) -> None:
        sessions = sorted(
            {*data.get("target_sessions", []), *(str(t["session_id"]) for t in targets)}
        )
        if len(sessions) > 256:
            raise ValueError("stop_target_budget_exceeded")
        encoded = json.dumps({**data, "target_sessions": sessions, "phase": "stopping"})
        if len(encoded.encode()) > 60000:
            raise ValueError("stop_metadata_budget_exceeded")
        data.update(target_sessions=sessions, phase="stopping")
        with self.database.connect_task_io() as connection:
            connection.execute(
                """UPDATE agent_safety_overrides SET diagnostics=%s,updated_at=clock_timestamp()
                WHERE deployment_namespace=%s AND session_id=%s AND reason=%s AND NOT shadow
                AND diagnostics::jsonb->>'operation_id'=%s""",
                (
                    json.dumps(data),
                    self.namespace,
                    UUID(data["session_id"]),
                    STOP_REASON,
                    data["operation_id"],
                ),
            )

    def revoke(self, target: dict[str, Any]) -> bool:
        sid = target["session_id"]
        with self.database.connect_task_io() as connection:
            connection.execute("SET LOCAL lock_timeout='250ms'")
            connection.execute("SET LOCAL statement_timeout='1500ms'")
            if not stop_requested(connection, self.namespace, sid):
                raise ValueError("stop_scope_changed")
            row = connection.execute(
                "SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) AS acquired",
                (f"{self.namespace}:{sid}",),
            ).fetchone()
            if row is None or not row["acquired"]:
                raise TimeoutError("stop_lease_busy")
            _lock_epoch(connection, self.namespace)
            lease, _ = _lock_lease_and_clock(connection, self.namespace, sid, update=True)
            exited = executors_exited(connection, self.namespace, sid, lease)
            if lease is not None:
                connection.execute(
                    """UPDATE worker_leases SET released_at=COALESCE(released_at,clock_timestamp())
                    WHERE deployment_namespace=%s AND session_id=%s""",
                    (self.namespace, sid),
                )
            return exited

    def instances(self, target: dict[str, Any]) -> list[dict[str, Any]]:
        with self.database.connect_task_io() as connection:
            return connection.execute(
                "SELECT * FROM runtime_instances WHERE deployment_namespace=%s AND session_id=%s "
                "AND status<>'removed' ORDER BY instance_id LIMIT 65",
                (self.namespace, target["session_id"]),
            ).fetchall()

    def cleanup_target(self, target: dict[str, Any], row: dict[str, Any]) -> CleanupTarget:
        host = target["binding"].host_capability
        return _target(
            row,
            {
                "session_id": target["session_id"],
                "tenant_id": host.namespace_id,
                "authority_issuer": host.authority_issuer,
                "workspace_id": host.host_context.workspace_ref,
                "revoked_epoch": row["control_plane_epoch"],
                "revoked_token": row["fencing_token"],
                "revoked_owner": row["owner_instance_id"],
            },
        )

    def removed(self, target: dict[str, Any], row: dict[str, Any], container_id: str) -> None:
        with self.database.connect_task_io() as connection:
            if not stop_requested(connection, self.namespace, target["session_id"]):
                raise ValueError("stop_scope_changed")
            connection.execute(
                """UPDATE runtime_instances SET container_id=%s,status='removed',
                removed_at=clock_timestamp() WHERE deployment_namespace=%s AND instance_id=%s
                AND session_id=%s AND engine_identity=%s AND container_name=%s
                AND (container_id IS NULL OR container_id=%s)""",
                (
                    container_id,
                    self.namespace,
                    row["instance_id"],
                    target["session_id"],
                    row["engine_identity"],
                    row["container_name"],
                    container_id,
                ),
            )

    def synchronize(self, data: dict[str, Any], target: dict[str, Any]) -> None:
        sid = SessionId(target["session_id"])
        # Physical exit/cleanup never wait on this bounded, existing 1 MiB reader.
        with postgres_deadline(monotonic() + 3):
            finish_command_read_state(
                self.database._dsn, deployment_namespace=self.namespace, session_id=sid
            )
            with self.database.connect() as connection:
                connection.execute("SET LOCAL lock_timeout='250ms'")
                connection.execute("SET LOCAL statement_timeout='1500ms'")
                state, lease, now = lock_cancellation_context(connection, self.namespace, sid)
                if state.session is None or not stop_requested(connection, self.namespace, sid):
                    raise ValueError("stop_scope_changed")
                if state.session.status.value in {"completed", "failed", "cancelled"}:
                    save_session_in_transaction(connection, self.namespace, state.session)
                    if state.workspace is not None:
                        save_workspace_in_transaction(connection, self.namespace, state.workspace)
                else:
                    operation = uuid5(NAMESPACE_URL, f"force-terminal:{data['operation_id']}:{sid}")
                    cancel_in_transaction(
                        connection,
                        self.namespace,
                        state,
                        lease,
                        now,
                        operation_id=operation,
                        command=False,
                    )
                # Cancellation is not a handled Worker boundary. Retain its receipts,
                # and release capacity only after revocation and exact executor exits.
                if (lease is None or lease["released_at"] is not None) and executors_exited(
                    connection, self.namespace, sid, lease
                ):
                    connection.execute(
                        """UPDATE session_command_pending SET status='cancelled'
                        WHERE deployment_namespace=%s AND session_id=%s AND status='pending'
                          AND accepted_sequence<=%s""",
                        (self.namespace, sid, state.through_sequence),
                    )

    def finish(
        self,
        data: dict[str, Any],
        *,
        execution: bool,
        lease: bool,
        sandbox: bool,
        synchronized: bool,
        code: str | None,
        progress: bool,
    ) -> None:
        now = datetime.now(UTC)
        complete = execution and lease and sandbox and synchronized and code is None
        attempts = 0 if progress else data.get("attempts", 0) + 1
        permanent = code in {
            "delegation_scope_conflict",
            "delegation_cycle",
            "stop_binding_changed",
            "stop_scope_changed",
            "stop_admission_unproven",
            "stop_target_budget_exceeded",
            "instance_identity_conflict",
        }
        exhausted = (
            permanent
            or attempts >= 16
            or now - datetime.fromisoformat(data["accepted_at"]) > timedelta(minutes=10)
        )
        updated = {
            **data,
            "execution": "stopped" if execution else "unconfirmed",
            "lease": "revoked" if lease else "unconfirmed",
            "sandbox": "cleaned" if sandbox else "pending",
            "synchronization": "synchronized" if synchronized else "pending",
            "phase": "done" if complete else "requires_reconciliation" if exhausted else "stopping",
            "attempts": attempts,
            "error_code": code,
            "next_attempt_at": (
                now + timedelta(seconds=min(30, 2 ** min(attempts, 5)))
            ).isoformat(),
        }
        encoded = json.dumps(updated)
        if len(encoded.encode()) > 60000:
            raise ValueError("stop_metadata_budget_exceeded")
        with self.database.connect_task_io() as connection:
            connection.execute(
                """UPDATE agent_safety_overrides SET diagnostics=%s,updated_at=clock_timestamp()
                WHERE deployment_namespace=%s AND session_id=%s AND reason=%s AND NOT shadow
                AND diagnostics::jsonb->>'operation_id'=%s""",
                (
                    encoded,
                    self.namespace,
                    UUID(data["session_id"]),
                    STOP_REASON,
                    data["operation_id"],
                ),
            )
