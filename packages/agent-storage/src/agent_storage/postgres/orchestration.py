"""PostgreSQL orchestration projections store (ORCH-PG-01).

Runs, plan revisions, nodes and dependencies persist atomically per
revision; run-status moves are CAS-guarded by the domain state machine;
result bundles and gate receipts are content-addressed by digest.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from agent_core.domain.identifiers import TaskId
from agent_core.domain.orchestration import (
    OrchestrationPlanSnapshot,
    OrchestrationRunStatus,
    assert_run_transition,
)
from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase


class OrchestrationStorageError(RuntimeError):
    """CAS or shape violations from the projection store."""


class PostgresOrchestrationStore:
    """Read/write store over the v27 projections."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    @property
    def deployment_namespace(self) -> str:
        return self._database.deployment_namespace

    def create_run(self, snapshot: OrchestrationPlanSnapshot) -> None:
        """Persist a validated run with its revision-1 plan atomically."""

        namespace = self.deployment_namespace
        with self._database.connect() as connection:
            inserted = connection.execute(
                """
                INSERT INTO orchestration_runs (
                    deployment_namespace, run_id, parent_task_id, status,
                    current_plan_revision
                ) VALUES (%s, %s, %s, 'validated', %s)
                ON CONFLICT (deployment_namespace, run_id) DO NOTHING
                RETURNING run_id
                """,
                (
                    namespace,
                    snapshot.run_ref,
                    str(snapshot.parent_task_id),
                    snapshot.plan_revision,
                ),
            ).fetchone()
            if inserted is None:
                raise OrchestrationStorageError("run already exists; append a revision")
            self._write_revision(connection, namespace, snapshot)

    def append_plan_revision(self, snapshot: OrchestrationPlanSnapshot) -> None:
        """Persist a newer revision and advance the run pointer atomically."""

        namespace = self.deployment_namespace
        with self._database.connect() as connection:
            row = connection.execute(
                """
                UPDATE orchestration_runs
                SET current_plan_revision = %s, updated_at = transaction_timestamp()
                WHERE deployment_namespace = %s AND run_id = %s
                    AND current_plan_revision = %s - 1
                RETURNING current_plan_revision
                """,
                (snapshot.plan_revision, namespace, snapshot.run_ref, snapshot.plan_revision),
            ).fetchone()
            if row is None:
                raise OrchestrationStorageError(
                    "plan revision must extend the current revision by exactly one"
                )
            self._write_revision(connection, namespace, snapshot)

    def transition_run(
        self,
        run_ref: str,
        current: OrchestrationRunStatus,
        target: OrchestrationRunStatus,
    ) -> OrchestrationRunStatus:
        """CAS-guarded run transition using the domain state machine."""

        assert_run_transition(current, target)
        namespace = self.deployment_namespace
        with self._database.connect() as connection:
            row = connection.execute(
                """
                UPDATE orchestration_runs
                SET status = %s, updated_at = transaction_timestamp()
                WHERE deployment_namespace = %s AND run_id = %s AND status = %s
                RETURNING status
                """,
                (target.value, namespace, run_ref, current.value),
            ).fetchone()
        if row is None:
            raise OrchestrationStorageError(
                f"run status CAS failed: {run_ref} is not {current.value}"
            )
        return target

    def get_snapshot(
        self,
        run_ref: str,
        *,
        revision: int | None = None,
    ) -> OrchestrationPlanSnapshot | None:
        namespace = self.deployment_namespace
        with self._database.connect() as connection:
            if revision is None:
                row = connection.execute(
                    """
                    SELECT snapshot_json FROM orchestration_plan_revisions
                    WHERE deployment_namespace = %s AND run_id = %s
                    ORDER BY plan_revision DESC LIMIT 1
                    """,
                    (namespace, run_ref),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT snapshot_json FROM orchestration_plan_revisions
                    WHERE deployment_namespace = %s AND run_id = %s AND plan_revision = %s
                    """,
                    (namespace, run_ref, revision),
                ).fetchone()
        if row is None:
            return None
        return OrchestrationPlanSnapshot.model_validate(row["snapshot_json"])

    def get_latest_revision(self, run_ref: str) -> int | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT current_plan_revision FROM orchestration_runs
                WHERE deployment_namespace = %s AND run_id = %s
                """,
                (self.deployment_namespace, run_ref),
            ).fetchone()
        return None if row is None else int(row["current_plan_revision"])

    def record_result_bundle(
        self,
        *,
        child_task_id: TaskId,
        result_digest: str,
        summary: str,
        artifact_refs: tuple[str, ...] = (),
        evidence_digests: tuple[str, ...] = (),
        gate_receipt_id: str | None = None,
    ) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO orchestration_result_bundles (
                    deployment_namespace, child_task_id, result_digest, summary,
                    artifact_refs, evidence_index, gate_receipt_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (deployment_namespace, child_task_id) DO UPDATE SET
                    result_digest = EXCLUDED.result_digest,
                    summary = EXCLUDED.summary,
                    artifact_refs = EXCLUDED.artifact_refs,
                    evidence_index = EXCLUDED.evidence_index,
                    gate_receipt_id = EXCLUDED.gate_receipt_id,
                    published_at = transaction_timestamp()
                """,
                (
                    self.deployment_namespace,
                    str(child_task_id),
                    result_digest,
                    summary,
                    Jsonb(list(artifact_refs)),
                    Jsonb(list(evidence_digests)),
                    gate_receipt_id,
                ),
            )

    def record_gate_receipt(
        self,
        *,
        child_task_id: TaskId,
        gate_name: str,
        passed: bool,
        reason_code: str,
    ) -> str:
        receipt_id = f"gate-{uuid4()}"
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO completion_gate_receipts (
                    deployment_namespace, receipt_id, child_task_id, gate_name,
                    passed, reason_code
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    self.deployment_namespace,
                    receipt_id,
                    str(child_task_id),
                    gate_name,
                    passed,
                    reason_code,
                ),
            )
        return receipt_id

    def get_result_bundle(self, child_task_id: TaskId) -> dict[str, object] | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT result_digest, summary, artifact_refs, evidence_index,
                    gate_receipt_id
                FROM orchestration_result_bundles
                WHERE deployment_namespace = %s AND child_task_id = %s
                """,
                (self.deployment_namespace, str(child_task_id)),
            ).fetchone()
        if row is None:
            return None
        return {
            "result_digest": row["result_digest"],
            "summary": row["summary"],
            "artifact_refs": tuple(row["artifact_refs"]),
            "evidence_digests": tuple(row["evidence_index"]),
            "gate_receipt_id": row["gate_receipt_id"],
        }

    def _write_revision(
        self,
        connection: Any,
        namespace: str,
        snapshot: OrchestrationPlanSnapshot,
    ) -> None:
        connection.execute(
            """
            INSERT INTO orchestration_plan_revisions (
                deployment_namespace, run_id, plan_revision, plan_digest,
                snapshot_json, validated_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                namespace,
                snapshot.run_ref,
                snapshot.plan_revision,
                snapshot.plan_digest,
                Jsonb(snapshot.model_dump(mode="json")),
                snapshot.validated_at or datetime.now(UTC),
            ),
        )
        for node in snapshot.nodes:
            connection.execute(
                """
                INSERT INTO orchestration_nodes (
                    deployment_namespace, run_id, plan_revision, node_key,
                    child_task_id, status
                ) VALUES (%s, %s, %s, %s, %s, 'blocked')
                ON CONFLICT (deployment_namespace, run_id, plan_revision, node_key)
                DO UPDATE SET child_task_id = EXCLUDED.child_task_id,
                    updated_at = transaction_timestamp()
                """,
                (
                    namespace,
                    snapshot.run_ref,
                    snapshot.plan_revision,
                    node.node_key,
                    str(node.child_task_id) if node.child_task_id else None,
                ),
            )
        for edge in snapshot.dependencies:
            connection.execute(
                """
                INSERT INTO orchestration_dependencies (
                    deployment_namespace, run_id, plan_revision, from_node, to_node
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    namespace,
                    snapshot.run_ref,
                    snapshot.plan_revision,
                    edge.from_node,
                    edge.to_node,
                ),
            )
