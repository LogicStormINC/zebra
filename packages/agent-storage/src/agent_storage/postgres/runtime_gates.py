"""Durable operator originals and namespace admission CAS; no executor or retries."""

from collections.abc import Callable
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from agent_core.domain.runtime_bundle_types import BundleScope
from agent_core.domain.runtime_gates import GateCommand, GateReceipt, GateState, gate_observation
from psycopg.types.json import Jsonb

from agent_storage.postgres.agent_registry import PostgresAgentRegistry
from agent_storage.postgres.host_management import (
    HostManagementConflict,
    HostManagementStore,
    HostManagementTrust,
    _canonical,
)
from agent_storage.postgres.runtime_gate_sources import (
    blocker_facts,
    build_work,
    candidate_snapshot,
    foreign_scope,
)
from agent_storage.postgres.worker_capability import _require_schema


class RuntimeGateStore:
    def __init__(self, dsn: str, scope: BundleScope, trust: HostManagementTrust) -> None:
        self.scope, self.trust = scope, trust
        self.approvals = HostManagementStore(dsn, deployment_namespace=scope.namespace_id)
        self.registry = PostgresAgentRegistry(dsn, deployment_namespace=scope.namespace_id)

    @contextmanager
    def _transaction(self) -> Any:
        with self.approvals._database.connect_task_io(timeout_seconds=2) as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            c.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (_canonical(self.approvals._binding(self.trust)),),
            )
            self.approvals._authorize(c, self.trust)
            yield c
            self.approvals._live(c, self.trust)

    def _gate(self, c: Any, *, update: bool = False) -> Any:
        _require_schema(c)
        epoch = c.execute(
            "SELECT epoch FROM control_plane_epochs WHERE deployment_namespace=%s FOR SHARE",
            (self.scope.namespace_id,),
        ).fetchone()
        if epoch is None:
            raise RuntimeError("EPOCH_UNAVAILABLE")
        row = c.execute(
            "SELECT * FROM runtime_namespace_gates WHERE deployment_namespace=%s FOR "
            + ("UPDATE" if update else "SHARE"),
            (self.scope.namespace_id,),
        ).fetchone()
        if row is None or row["scope"] != self.scope.model_dump(mode="json"):
            raise PermissionError("GATE_SCOPE_NOT_INITIALIZED")
        return row

    def initialize(self) -> None:
        with self._transaction() as c:
            _require_schema(c)
            if foreign_scope(c, self.scope):
                raise PermissionError("EXCLUSIVE_NAMESPACE_REQUIRED")
            row = c.execute(
                "SELECT scope FROM runtime_namespace_gates "
                "WHERE deployment_namespace=%s FOR UPDATE",
                (self.scope.namespace_id,),
            ).fetchone()
            if row is None or row["scope"] not in (None, self.scope.model_dump(mode="json")):
                raise PermissionError("EXCLUSIVE_NAMESPACE_REQUIRED")
            c.execute(
                "UPDATE runtime_namespace_gates SET scope=%s WHERE deployment_namespace=%s",
                (Jsonb(self.scope.model_dump(mode="json")), self.scope.namespace_id),
            )

    def change(
        self, command: GateCommand, digest: str, recheck: Callable[[], None]
    ) -> dict[str, Any]:
        with self._transaction() as c:
            gate = self._gate(c, update=True)
            if command.action != "open" and foreign_scope(c, self.scope):
                raise PermissionError("EXCLUSIVE_NAMESPACE_REQUIRED")
            state = GateState(revision=gate["revision"], admission=gate["mode"]).apply(command)
            if c.execute(
                """
    SELECT 1 FROM runtime_gate_operations WHERE deployment_namespace=%s AND
    operation_id=%s
    """,
                (self.scope.namespace_id, command.operation_id),
            ).fetchone():
                raise HostManagementConflict("ORIGINAL_GET_REQUIRED")
            count = c.execute(
                "SELECT count(*) AS n FROM runtime_gate_operations WHERE deployment_namespace=%s",
                (self.scope.namespace_id,),
            ).fetchone()["n"]
            # ponytail: 128 originals with the last slot reserved for explicit open.
            # Add operator archival before raising the bound; never strand closed admission.
            if count >= 128 or count >= 127 and command.action != "open":
                raise OverflowError("GATE_RETENTION_LIMIT")
            if command.candidate is not None:
                candidate_snapshot(c, self.registry, self.scope, command.candidate)
            revision, mode = state.revision, state.admission
            original = {
                "operationId": str(command.operation_id),
                "action": command.action,
                "inputDigest": "sha256:" + digest,
                "gateRevision": revision,
                "admission": mode,
                "actor": self.trust.host_app_id,
                "trustRevision": self.trust.revision,
            }
            original = GateReceipt.model_validate(original).model_dump(mode="json", by_alias=True)
            recheck()
            c.execute(
                "UPDATE runtime_namespace_gates SET revision=%s,mode=%s "
                "WHERE deployment_namespace=%s",
                (revision, mode, self.scope.namespace_id),
            )
            c.execute(
                """
    INSERT INTO
    runtime_gate_operations(deployment_namespace,operation_id,request,input_digest,receipt)
    VALUES(%s,%s,%s,%s,%s)
    """,
                (
                    self.scope.namespace_id,
                    command.operation_id,
                    Jsonb(command.model_dump(mode="json")),
                    digest,
                    Jsonb(original),
                ),
            )
            self.approvals._live(c, self.trust)
            return {"original": original}

    def read(self, operation: str | None = None) -> dict[str, Any]:
        if operation is not None and str(UUID(operation)) != operation:
            raise ValueError("INVALID_OPERATION")
        with self._transaction() as c:
            gate = self._gate(c)
            original = None
            workers = []
            complete = False
            facts = blocker_facts(c, self.scope.namespace_id)
            facts["scope_conflict"] = int(foreign_scope(c, self.scope))
            if operation is not None:
                record = c.execute(
                    """
    SELECT request,input_digest,receipt FROM runtime_gate_operations WHERE
    deployment_namespace=%s AND operation_id=%s
    """,
                    (self.scope.namespace_id, operation),
                ).fetchone()
                if record is None:
                    raise LookupError("NOT_FOUND")
                try:
                    command = GateCommand.model_validate(record["request"])
                    receipt = GateReceipt.model_validate(record["receipt"])
                except ValueError:
                    raise RuntimeError("CORRUPT_ORIGINAL") from None
                if (
                    str(command.operation_id) != operation
                    or receipt.operation_id != command.operation_id
                    or receipt.action != command.action
                    or receipt.gate_revision
                    != command.expected_revision + (command.action != "assess")
                    or receipt.input_digest != "sha256:" + record["input_digest"]
                ):
                    raise RuntimeError("CORRUPT_ORIGINAL")
                original = receipt.model_dump(mode="json", by_alias=True)
                if command.candidate is not None:
                    try:
                        work = build_work(
                            c,
                            self.registry,
                            self.scope,
                            operation,
                            command.candidate,
                            gate["revision"],
                        )
                    except ValueError:
                        facts["candidate_unavailable"] = 1
                    else:
                        facts = work.blockers
                        complete = work.source_complete
                        workers = c.execute(
                            """
    SELECT w.process_id,w.compatible,w.reason,w.expires_at,w.runtime_class FROM
    runtime_gate_worker_observations w JOIN control_plane_epochs e
    USING(deployment_namespace,epoch) WHERE w.deployment_namespace=%s AND
    w.operation_id=%s AND w.fingerprint=%s AND w.expires_at>clock_timestamp() ORDER BY
    process_id LIMIT 17
    """,
                            (self.scope.namespace_id, operation, work.fingerprint),
                        ).fetchall()
                        if len(workers) > 16:
                            workers = []
                            complete = False
                            facts["worker_overflow"] = 1
                        workers = [
                            {
                                "processId": str(w["process_id"]),
                                "runtimeClass": w["runtime_class"],
                                "compatible": w["compatible"],
                                "reason": w["reason"],
                                "expiresAt": w["expires_at"].isoformat(),
                            }
                            for w in workers
                        ]
            result = gate_observation(gate["mode"], facts, workers, source_complete=complete)
            self.approvals._live(c, self.trust)
            return {
                "original": original,
                "gateRevision": gate["revision"],
                "observedAt": c.execute("SELECT clock_timestamp() AS now")
                .fetchone()["now"]
                .isoformat(),
                **result,
            }
