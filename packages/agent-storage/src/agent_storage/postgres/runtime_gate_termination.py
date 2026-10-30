"""Original commit and exclusion proof serialize at the same namespace root."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from agent_core.domain.runtime_gate_termination import (
    GateTerminationCommand,
    GateTerminationReceipt,
)
from agent_core.domain.runtime_gates import GateConflict, GateReceipt
from psycopg.types.json import Jsonb

from agent_storage.postgres.host_management import HostManagementConflict
from agent_storage.postgres.runtime_gates import RuntimeGateStore


class RuntimeGateTerminationStore(RuntimeGateStore):
    def terminate(
        self, command: GateTerminationCommand, digest: str, recheck: Callable[[], None]
    ) -> dict[str, Any]:
        with self._transaction() as c:
            gate = self._gate(c, update=True)
            if gate["revision"] != command.expected_gate_revision:
                raise GateConflict("GATE_CAS_CONFLICT")
            if c.execute(
                """SELECT 1 FROM runtime_gate_terminations WHERE deployment_namespace=%s
 AND (termination_id=%s OR operation_id=%s)""",
                (self.scope.namespace_id, command.termination_id, command.original.operation_id),
            ).fetchone():
                raise HostManagementConflict("ORIGINAL_TERMINATION_GET_REQUIRED")
            if (
                c.execute(
                    "SELECT count(*) AS n FROM runtime_gate_terminations "
                    "WHERE deployment_namespace=%s",
                    (self.scope.namespace_id,),
                ).fetchone()["n"]
                >= 128
            ):
                raise OverflowError("TERMINATION_RETENTION_LIMIT")
            prior = c.execute(
                "SELECT receipt,input_digest FROM runtime_gate_operations "
                "WHERE deployment_namespace=%s AND operation_id=%s",
                (self.scope.namespace_id, command.original.operation_id),
            ).fetchone()
            original = None
            if prior is not None:
                if "sha256:" + prior["input_digest"] != command.original_digest:
                    raise GateConflict("ORIGINAL_INPUT_MISMATCH")
                original = GateReceipt.model_validate(prior["receipt"])
                if (
                    original.operation_id != command.original.operation_id
                    or original.action != command.original.action
                    or original.input_digest != command.original_digest
                    or original.gate_revision
                    != command.original.expected_revision + (command.original.action != "assess")
                ):
                    raise RuntimeError("CORRUPT_ORIGINAL")
            receipt = GateTerminationReceipt.model_validate(
                {
                    "terminationId": str(command.termination_id),
                    "operationId": str(command.original.operation_id),
                    "inputDigest": "sha256:" + digest,
                    "originalInputDigest": command.original_digest,
                    "outcome": "already_committed" if original is not None else "no_gate_commit",
                    "gateRevision": gate["revision"],
                    "actor": self.trust.host_app_id,
                    "trustRevision": self.trust.revision,
                    "lateSubmissionFenced": True,
                    "proofScope": "original_gate_command_only",
                    "original": original.model_dump(mode="json", by_alias=True)
                    if original
                    else None,
                }
            ).model_dump(mode="json", by_alias=True)
            recheck()
            # A tuple change is essential: an older repeatable-read snapshot must abort,
            # even though termination does not advance the logical admission revision.
            c.execute(
                "UPDATE runtime_namespace_gates SET revision=revision "
                "WHERE deployment_namespace=%s",
                (self.scope.namespace_id,),
            )
            c.execute(
                """INSERT INTO runtime_gate_terminations
 (deployment_namespace,termination_id,operation_id,request,input_digest,receipt)
 VALUES(%s,%s,%s,%s,%s,%s)""",
                (
                    self.scope.namespace_id,
                    command.termination_id,
                    command.original.operation_id,
                    Jsonb(command.model_dump(mode="json")),
                    digest,
                    Jsonb(receipt),
                ),
            )
            return {"original": receipt}

    def read(self, operation: str | None = None) -> dict[str, Any]:
        if operation is None or str(UUID(operation)) != operation:
            raise ValueError("INVALID_OPERATION")
        with self._transaction() as c:
            self._gate(c)
            record = c.execute(
                """SELECT operation_id,request,input_digest,receipt FROM runtime_gate_terminations
 WHERE deployment_namespace=%s AND termination_id=%s""",
                (self.scope.namespace_id, operation),
            ).fetchone()
            if record is None:
                raise LookupError("NOT_FOUND")
            command = GateTerminationCommand.model_validate(record["request"])
            receipt = GateTerminationReceipt.model_validate(record["receipt"])
            if (
                str(command.termination_id) != operation
                or receipt.termination_id != command.termination_id
                or receipt.operation_id != record["operation_id"]
                or receipt.operation_id != command.original.operation_id
                or receipt.original_input_digest != command.original_digest
                or receipt.input_digest != "sha256:" + record["input_digest"]
                or receipt.gate_revision != command.expected_gate_revision
                or receipt.original is not None
                and (
                    receipt.original.action != command.original.action
                    or receipt.original.gate_revision
                    != command.original.expected_revision + (command.original.action != "assess")
                )
            ):
                raise RuntimeError("CORRUPT_TERMINATION")
            return {"original": receipt.model_dump(mode="json", by_alias=True)}
