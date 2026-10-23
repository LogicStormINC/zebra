"""Native Eval claims and atomic evidence receipts; execution never holds a lock."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from agent_storage.postgres.agent_registry import AgentDefinitionEvalEvidence, PostgresAgentRegistry
from agent_storage.postgres.host_management import HostManagementConflict, HostManagementTrust
from agent_storage.postgres.publication import PublicationStore, lock_definition
from agent_storage.postgres.work_unit import postgres_transaction_work_unit


class ScriptEvaluationStore(PublicationStore):
    def __init__(self, dsn: str, namespace: str) -> None:
        super().__init__(dsn, namespace)
        self.registry = PostgresAgentRegistry(dsn, deployment_namespace=namespace)

    def initialize(self) -> None:
        """Operator-only additive initialization. Never called by API/Worker startup."""
        with self.database.connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS native_script_eval_operations (
                deployment_namespace text NOT NULL,actor text NOT NULL,operation_id uuid NOT NULL,
                authority_issuer text NOT NULL,namespace_id text NOT NULL,
                definition_id uuid NOT NULL,
                version_id uuid NOT NULL,payload_digest text NOT NULL,status text NOT NULL
                CHECK(status IN ('unknown','completed')),result jsonb NOT NULL,
                PRIMARY KEY(deployment_namespace,actor,operation_id))""")
            connection.execute("""CREATE INDEX IF NOT EXISTS native_script_eval_pending
                ON native_script_eval_operations(deployment_namespace,authority_issuer,
                namespace_id,definition_id,version_id,status)""")

    def observe(self, trust: HostManagementTrust, operation: UUID) -> dict[str, Any] | None:
        with self.approvals.authorized(trust) as connection:
            row = self._operation(connection, trust, operation)
            self.approvals._live(connection, trust)
            return None if row is None else dict(row["result"])

    def claim(
        self,
        trust: HostManagementTrust,
        operation: UUID,
        digest: str,
        scope: tuple[str, str, Any],
        version: UUID,
        recheck: Callable[[], None],
    ) -> tuple[bool, dict[str, Any]]:
        with self.approvals.authorized(trust) as connection:
            lock_definition(connection, scope)
            recheck()
            row = self._operation(connection, trust, operation)
            if row is not None:
                if row["payload_digest"] != digest:
                    raise HostManagementConflict("EVAL_OPERATION_CONFLICT")
                self.approvals._live(connection, trust)
                return False, dict(row["result"])
            pending = connection.execute(
                "SELECT 1 FROM native_script_eval_operations WHERE deployment_namespace=%s "
                "AND authority_issuer=%s AND namespace_id=%s AND definition_id=%s "
                "AND version_id=%s AND status='unknown' LIMIT 1",
                (self.database.deployment_namespace, *scope, version),
            ).fetchone()
            if pending is not None:
                raise HostManagementConflict("EVAL_UNKNOWN_BLOCKED")
            count = connection.execute(
                "SELECT count(*) AS count FROM native_script_eval_operations "
                "WHERE deployment_namespace=%s AND authority_issuer=%s AND namespace_id=%s "
                "AND definition_id=%s AND version_id=%s",
                (self.database.deployment_namespace, *scope, version),
            ).fetchone()
            # ponytail: 1024 retained attempts per Version; explicit archival is needed to raise it.
            if count is not None and count["count"] >= 1024:
                raise HostManagementConflict("EVAL_CAPACITY")
            result = {
                "operationId": str(operation),
                "status": "unknown",
                "inputDigest": digest,
                "versionId": str(version),
                "definitionId": str(scope[2]),
            }
            connection.execute(
                "INSERT INTO native_script_eval_operations VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.database.deployment_namespace,
                    trust.host_app_id,
                    operation,
                    *scope,
                    version,
                    digest,
                    "unknown",
                    Jsonb(result),
                ),
            )
            self.approvals._live(connection, trust)
            return True, result

    def complete(
        self,
        trust: HostManagementTrust,
        operation: UUID,
        digest: str,
        evidence: AgentDefinitionEvalEvidence,
        summary: dict[str, object],
        recheck: Callable[[], None],
    ) -> dict[str, Any]:
        scope = (evidence.authority_issuer, evidence.namespace_id, evidence.definition_id)
        with self.approvals.authorized(trust) as connection:
            lock_definition(connection, scope)
            recheck()
            row = self._operation(connection, trust, operation)
            if (
                row is None
                or row["payload_digest"] != digest
                or row["status"] != "unknown"
                or row["version_id"] != evidence.version_id
                or row["definition_id"] != evidence.definition_id
                or row["authority_issuer"] != evidence.authority_issuer
                or row["namespace_id"] != evidence.namespace_id
            ):
                raise HostManagementConflict("EVAL_OPERATION_CONFLICT")
            result = dict(row["result"]) | {
                "status": "completed",
                "evidenceId": str(evidence.evidence_id),
                "summary": summary,
            }
            with postgres_transaction_work_unit(self.database, connection):
                self.registry.record_eval_evidence(evidence)
            connection.execute(
                "UPDATE native_script_eval_operations SET status='completed',result=%s "
                "WHERE deployment_namespace=%s AND actor=%s AND operation_id=%s",
                (Jsonb(result), self.database.deployment_namespace, trust.host_app_id, operation),
            )
            self.approvals._live(connection, trust)
            return result

    def _operation(self, connection: Any, trust: HostManagementTrust, operation: UUID) -> Any:
        return connection.execute(
            "SELECT * FROM native_script_eval_operations WHERE deployment_namespace=%s "
            "AND actor=%s AND operation_id=%s",
            (self.database.deployment_namespace, trust.host_app_id, operation),
        ).fetchone()
