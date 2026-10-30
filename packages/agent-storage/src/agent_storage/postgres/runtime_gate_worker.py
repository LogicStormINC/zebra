"""Worker-only observations. No HTTP route can supply a compatibility attestation."""

from collections.abc import Callable
from uuid import UUID

from agent_core.domain.runtime_bundle_types import BundleScope
from agent_core.domain.runtime_gates import GateCommand, GateWork

from agent_storage.postgres.agent_registry import PostgresAgentRegistry
from agent_storage.postgres.runtime_gate_sources import build_work
from agent_storage.postgres.worker_capability import _require_schema


class RuntimeGateWorkerStore:
    def __init__(self, dsn: str, scope: BundleScope, runtime_class: str) -> None:
        self.runtime_class = runtime_class
        self.registry = PostgresAgentRegistry(dsn, deployment_namespace=scope.namespace_id)
        self.scope = scope
        self.epoch: UUID | None = None

    def tick(self, process: UUID, evaluate: Callable[[GateWork], tuple[bool, str]]) -> None:
        with self.registry._database.connect_task_io(timeout_seconds=2) as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            _require_schema(c)
            gate = c.execute(
                "SELECT * FROM runtime_namespace_gates WHERE deployment_namespace=%s FOR SHARE",
                (self.scope.namespace_id,),
            ).fetchone()
            if gate is None or gate["scope"] != self.scope.model_dump(mode="json"):
                return
            epoch_row = c.execute(
                "SELECT epoch FROM control_plane_epochs WHERE deployment_namespace=%s FOR SHARE",
                (self.scope.namespace_id,),
            ).fetchone()
            if epoch_row is None:
                raise RuntimeError("EPOCH_UNAVAILABLE")
            epoch = epoch_row["epoch"]
            if self.epoch is None:
                self.epoch = epoch
            if epoch != self.epoch:
                raise RuntimeError("WORKER_EPOCH_CHANGED")
            requests = c.execute(
                """
    SELECT operation_id,request FROM runtime_gate_operations WHERE
    deployment_namespace=%s AND request->>'action'='assess' ORDER BY created_at
    DESC,operation_id DESC LIMIT 4
    """,
                (self.scope.namespace_id,),
            ).fetchall()
            for request in requests:
                command = GateCommand.model_validate(request["request"])
                if command.candidate is None:
                    continue
                try:
                    work = build_work(
                        c,
                        self.registry,
                        self.scope,
                        str(request["operation_id"]),
                        command.candidate,
                        gate["revision"],
                    )
                except ValueError:
                    continue
                compatible, reason = evaluate(work)
                if reason not in {"compatible", "incompatible", "source_unproven"}:
                    raise ValueError("INVALID_WORKER_OBSERVATION")
                c.execute(
                    """
    DELETE FROM runtime_gate_worker_observations WHERE deployment_namespace=%s AND
    expires_at<=clock_timestamp()
    """,
                    (self.scope.namespace_id,),
                )
                count_row = c.execute(
                    """
    SELECT count(*) AS n FROM runtime_gate_worker_observations WHERE
    deployment_namespace=%s AND operation_id=%s AND process_id<>%s
    """,
                    (self.scope.namespace_id, command.operation_id, process),
                ).fetchone()
                if count_row is None:
                    raise RuntimeError("OBSERVATION_COUNT_UNAVAILABLE")
                count = count_row["n"]
                if count >= 16:
                    raise OverflowError("WORKER_OBSERVATION_CAPACITY")
                c.execute(
                    """
    INSERT INTO runtime_gate_worker_observations
    VALUES(%s,%s,%s,%s,%s,%s,clock_timestamp()+interval '15 seconds',%s,%s) ON
    CONFLICT(deployment_namespace,operation_id,process_id) DO UPDATE SET
    fingerprint=EXCLUDED.fingerprint,compatible=EXCLUDED.compatible,reason=EXCLUDED.reason,expires_at=EXCLUDED.expires_at,epoch=EXCLUDED.epoch,runtime_class=EXCLUDED.runtime_class
    """,
                    (
                        self.scope.namespace_id,
                        command.operation_id,
                        process,
                        work.fingerprint,
                        compatible,
                        reason,
                        epoch,
                        self.runtime_class,
                    ),
                )

    def close(self, process: UUID) -> None:
        with self.registry._database.connect_task_io(timeout_seconds=2) as c:
            c.execute(
                """
    DELETE FROM runtime_gate_worker_observations WHERE deployment_namespace=%s AND
    process_id=%s
    """,
                (self.scope.namespace_id, process),
            )
