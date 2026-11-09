"""Exact cloud Eval resources, separate from business Task leases and receipts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from uuid import UUID

from agent_storage.postgres.host_management import HostManagementTrust, HostManagementUnavailable

if TYPE_CHECKING:
    from agent_storage.postgres.script_evaluation import ScriptEvaluationStore


def initialize_cloud_eval(c: Any) -> None:
    c.execute("""CREATE TABLE IF NOT EXISTS native_script_eval_cloud_holds(
        deployment_namespace text NOT NULL,actor text NOT NULL,operation_id uuid NOT NULL,
        PRIMARY KEY(deployment_namespace,actor,operation_id),FOREIGN KEY
        (deployment_namespace,actor,operation_id) REFERENCES native_script_eval_operations)""")
    c.execute("""CREATE TABLE IF NOT EXISTS native_script_eval_instances(
        deployment_namespace text NOT NULL,actor text NOT NULL,operation_id uuid NOT NULL,
        instance_id uuid NOT NULL,engine_id text NOT NULL,spec_digest text NOT NULL,
        container_id text,status text NOT NULL CHECK(status IN ('reserved','created','removed')),
        PRIMARY KEY(deployment_namespace,actor,operation_id,instance_id),FOREIGN KEY
        (deployment_namespace,actor,operation_id) REFERENCES native_script_eval_cloud_holds)""")
    c.execute("""CREATE TABLE IF NOT EXISTS native_script_eval_instance_events(
        deployment_namespace text NOT NULL,actor text NOT NULL,operation_id uuid NOT NULL,
        instance_id uuid NOT NULL,status text NOT NULL,container_id text,
        occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        PRIMARY KEY(deployment_namespace,actor,operation_id,instance_id,status))""")
    c.execute("""CREATE OR REPLACE FUNCTION native_script_eval_instance_immutable()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION
        'Eval resource observations are immutable'; END $$""")
    c.execute(
        "DROP TRIGGER IF EXISTS native_script_eval_instance_immutable "
        "ON native_script_eval_instance_events"
    )
    c.execute("""CREATE TRIGGER native_script_eval_instance_immutable BEFORE UPDATE OR DELETE
        ON native_script_eval_instance_events FOR EACH ROW EXECUTE FUNCTION
        native_script_eval_instance_immutable()""")


def require_cloud_eval_schema(c: Any) -> None:
    c.execute(
        "SELECT h.operation_id,i.instance_id,e.status FROM native_script_eval_cloud_holds h "
        "LEFT JOIN native_script_eval_instances i USING(deployment_namespace,actor,operation_id) "
        "LEFT JOIN native_script_eval_instance_events e "
        "USING(deployment_namespace,actor,operation_id,instance_id) LIMIT 0"
    )


def require_no_cloud_eval(c: Any, namespace: str) -> None:
    if (
        c.execute("SELECT to_regclass('native_script_eval_cloud_holds') AS name").fetchone()["name"]
        is None
    ):
        return  # Existing installations cannot dispatch the new cloud Eval profile.
    if c.execute(
        """SELECT 1 FROM native_script_eval_cloud_holds h JOIN
        native_script_eval_operations o USING(deployment_namespace,actor,operation_id)
        WHERE h.deployment_namespace=%s AND o.status<>'completed' LIMIT 1""",
        (namespace,),
    ).fetchone():
        raise HostManagementUnavailable("CLOUD_EVAL_SOURCE_INCOMPLETE")


def require_eval_resources_settled(c: Any, namespace: str, actor: str, operation: UUID) -> None:
    if (
        c.execute("SELECT to_regclass('native_script_eval_instances') AS name").fetchone()["name"]
        is None
    ):
        return
    if c.execute(
        """SELECT 1 FROM native_script_eval_instances WHERE
        deployment_namespace=%s AND actor=%s AND operation_id=%s AND status<>'removed'
        LIMIT 1""",
        (namespace, actor, operation),
    ).fetchone():
        raise HostManagementUnavailable("EVAL_RESOURCE_UNKNOWN")


class PostgresScriptEvalInstances:
    def __init__(
        self,
        store: ScriptEvaluationStore,
        trust: HostManagementTrust,
        operation: UUID,
        digest: str,
        engine: str,
    ) -> None:
        if len(engine) != 64 or any(x not in "0123456789abcdef" for x in engine):
            raise ValueError("invalid Eval engine identity")
        self.store, self.trust = store, trust
        self.operation, self.digest, self.engine_identity = operation, digest, engine
        self.key = (store.database.deployment_namespace, trust.host_app_id, operation)

    def _authorize(self, c: Any) -> None:
        row = self.store._operation(c, self.trust, self.operation, lock=True)
        if row is None or row["status"] != "unknown" or row["payload_digest"] != self.digest:
            raise HostManagementUnavailable("EVAL_ORIGINAL_NOT_ACTIVE")
        if (
            c.execute(
                "SELECT 1 FROM native_script_eval_cloud_holds WHERE "
                "deployment_namespace=%s AND actor=%s AND operation_id=%s",
                self.key,
            ).fetchone()
            is None
        ):
            raise HostManagementUnavailable("EVAL_CLOUD_HOLD_REQUIRED")

    def reserve(self, instance_id: str, session_id: str, spec_digest: str) -> Mapping[str, str]:
        UUID(instance_id)
        if session_id != str(self.operation) or not spec_digest or len(spec_digest) > 128:
            raise ValueError("Eval instance differs from original")
        with self.store.approvals.authorized(self.trust) as c:
            self._authorize(c)
            c.execute(
                "SELECT 1 FROM native_script_eval_operations WHERE deployment_namespace=%s "
                "AND actor=%s AND operation_id=%s FOR UPDATE",
                self.key,
            )
            count = c.execute(
                "SELECT count(*) AS n FROM native_script_eval_instances WHERE "
                "deployment_namespace=%s AND actor=%s AND operation_id=%s",
                self.key,
            ).fetchone()["n"]
            if count >= 64:
                raise HostManagementUnavailable("EVAL_RESOURCE_CAPACITY")
            c.execute(
                "INSERT INTO native_script_eval_instances "
                "VALUES(%s,%s,%s,%s,%s,%s,NULL,'reserved')",
                (*self.key, instance_id, self.engine_identity, spec_digest),
            )
            self._event(c, instance_id, "reserved", None)
        return {
            "zebra.agent.namespace": self.key[0],
            "zebra.agent.eval-operation": str(self.operation),
        }

    def _instance(self, c: Any, instance: str) -> Any:
        row = c.execute(
            "SELECT * FROM native_script_eval_instances WHERE deployment_namespace=%s "
            "AND actor=%s AND operation_id=%s AND instance_id=%s FOR UPDATE",
            (*self.key, instance),
        ).fetchone()
        if row is None or row["engine_id"] != self.engine_identity:
            raise ValueError("Eval instance ownership differs")
        return row

    @staticmethod
    def _cid(cid: str) -> None:
        if len(cid) != 64 or any(x not in "0123456789abcdef" for x in cid):
            raise ValueError("exact Eval container identity required")

    def _event(self, c: Any, instance: str, status: str, cid: str | None) -> None:
        c.execute(
            "INSERT INTO native_script_eval_instance_events "
            "(deployment_namespace,actor,operation_id,instance_id,status,container_id) "
            "VALUES(%s,%s,%s,%s,%s,%s)",
            (*self.key, instance, status, cid),
        )

    def created(self, instance_id: str, container_id: str) -> None:
        self._record(instance_id, container_id, "created")

    def removed(self, instance_id: str, container_id: str) -> None:
        self._record(instance_id, container_id, "removed")

    def _record(self, instance: str, cid: str, status: str) -> None:
        self._cid(cid)
        # Late exact observations remain recordable after revocation; they do not
        # authorize start or turn missing/unknown objects into deletion proof.
        with self.store.database.connect() as c:
            row = self._instance(c, instance)
            if (
                row["container_id"] not in (None, cid)
                or row["status"] == "removed"
                and status != "removed"
            ):
                raise ValueError("Eval resource history conflicts")
            if row["status"] == status:
                return
            c.execute(
                "UPDATE native_script_eval_instances SET container_id=%s,status=%s WHERE "
                "deployment_namespace=%s AND actor=%s AND operation_id=%s AND instance_id=%s",
                (cid, status, *self.key, instance),
            )
            self._event(c, instance, status, cid)

    def authorize(self, instance_id: str, container_id: str) -> None:
        self._cid(container_id)
        with self.store.approvals.authorized(self.trust) as c:
            self._authorize(c)
            row = self._instance(c, instance_id)
            if row["status"] != "created" or row["container_id"] != container_id:
                raise ValueError("Eval instance is not authorized")
