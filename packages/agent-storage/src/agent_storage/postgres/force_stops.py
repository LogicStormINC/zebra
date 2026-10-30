"""Authenticated, durable watchdog stop before any potentially blocked event writes."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import TaskId
from agent_core.domain.task_bindings import require_task_host_context

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.direct_control import PostgresDirectControl
from agent_storage.postgres.force_stop_signal import STOP_REASON


def _require_task_scope(context: Any) -> None:
    if context is None:
        raise ValueError("force stop requires a fresh Host grant")
    context.require_scope("agent.run")
    if any(ref.resource_type == "run" for ref in context.resource_refs):
        raise ValueError("Task-wide force stop requires Task-scoped authority")


class PostgresForceStops:
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self.database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self.control = PostgresDirectControl(dsn, deployment_namespace=deployment_namespace)

    def request(
        self,
        task_id: UUID,
        context: Any,
        key: str,
        *,
        authority_issuer: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(key, str) or not key.strip() or len(key) > 240:
            raise ValueError("force stop requires a bounded idempotency key")
        _require_task_scope(context)
        binding = self.control.load_task_binding(TaskId(task_id))
        if binding is None:
            raise ValueError("force stop Task was not found")
        authorized_at = datetime.now(UTC)
        require_task_host_context(
            binding,
            context,
            task_id=str(task_id),
            now=authorized_at,
            authority_issuer=authority_issuer,
        )
        namespace = self.database.deployment_namespace
        with self.database.connect_task_io() as connection:
            connection.execute("SET LOCAL lock_timeout='250ms'")
            connection.execute("SET LOCAL statement_timeout='1500ms'")
            request_hash = sha256(f"force-stop:{task_id}".encode()).hexdigest()
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"force-stop:{namespace}:{key}",),
            )
            prior_receipt = connection.execute(
                "SELECT request_hash,response_body FROM control_plane_idempotency_records "
                "WHERE deployment_namespace=%s AND action='force_stop' AND idempotency_key=%s",
                (namespace, key),
            ).fetchone()
            if prior_receipt is not None:
                if prior_receipt["request_hash"] != request_hash:
                    raise ValueError("force stop idempotency conflict")
                return cast(dict[str, Any], prior_receipt["response_body"])
            row = connection.execute(
                "SELECT active_segment_id FROM agent_tasks "
                "WHERE deployment_namespace=%s AND task_id=%s",
                (namespace, task_id),
            ).fetchone()
            if row is None:
                raise ValueError("force stop Task was not found")
            sid = row["active_segment_id"]
            prior = connection.execute(
                "SELECT diagnostics FROM agent_safety_overrides WHERE deployment_namespace=%s "
                "AND session_id=%s AND reason=%s AND kind='watchdog' AND NOT shadow",
                (namespace, sid, STOP_REASON),
            ).fetchone()
            if prior is not None:
                data = json.loads(prior["diagnostics"])
                if data["task_id"] != str(task_id):
                    raise ValueError("force stop scope changed")
            else:
                data = {
                    "operation_id": str(uuid5(NAMESPACE_URL, f"force:{namespace}:{task_id}:{key}")),
                    "task_id": str(task_id),
                    "session_id": str(sid),
                    "binding_digest": binding.binding_digest,
                    "authority_issuer": binding.host_capability.authority_issuer,
                    "tenant_id": context.namespace_id,
                    "workspace_id": context.workspace_ref,
                    "phase": "requested",
                    "attempts": 0,
                    "context": HostContextEnvelope.model_validate(
                        {
                            **context.model_dump(mode="json"),
                            "scopes": ["agent.run"],
                            "resource_refs": [
                                ref.model_dump(mode="json")
                                for ref in context.resource_refs
                                if ref.resource_type in {"principal", "thread"}
                            ],
                        }
                    ).model_dump(mode="json"),
                    "accepted_at": authorized_at.isoformat(),
                }
            # No FK to the event stream, and no Session/lease/stream lock: this
            # signal must commit even if the harness holds those locks forever.
            if len(json.dumps(data).encode()) > 60000:
                raise ValueError("force stop metadata budget exceeded")
            saved = connection.execute(
                """INSERT INTO agent_safety_overrides
                (deployment_namespace,session_id,kind,reason,diagnostics,attempts,shadow,created_at,updated_at)
                VALUES (%s,%s,'watchdog',%s,%s,0,FALSE,clock_timestamp(),clock_timestamp())
                ON CONFLICT(deployment_namespace,session_id) DO UPDATE SET
                kind='watchdog',reason=EXCLUDED.reason,diagnostics=EXCLUDED.diagnostics,
                shadow=FALSE,updated_at=clock_timestamp()
                WHERE agent_safety_overrides.reason<>EXCLUDED.reason
                 OR agent_safety_overrides.shadow
                RETURNING diagnostics""",
                (namespace, sid, STOP_REASON, json.dumps(data)),
            ).fetchone()
            if saved is None:
                saved = connection.execute(
                    "SELECT diagnostics FROM agent_safety_overrides "
                    "WHERE deployment_namespace=%s AND session_id=%s",
                    (namespace, sid),
                ).fetchone()
            if saved is None:
                raise RuntimeError("force stop record was not retained")
            result = self.public(json.loads(saved["diagnostics"]))
            connection.execute(
                """INSERT INTO control_plane_idempotency_records
                (deployment_namespace,action,idempotency_key,request_hash,status_code,response_body,created_at)
                VALUES (%s,'force_stop',%s,%s,%s,%s::jsonb,clock_timestamp())""",
                (
                    namespace,
                    key,
                    request_hash,
                    200 if result["state"] == "stopped" else 202,
                    json.dumps(result),
                ),
            )
            return result

    def status(
        self, task_id: UUID, context: Any, *, authority_issuer: str | None = None
    ) -> dict[str, Any]:
        binding = self.control.load_task_binding(TaskId(task_id))
        if binding is None:
            raise ValueError("force stop Task was not found")
        _require_task_scope(context)
        require_task_host_context(
            binding,
            context,
            task_id=str(task_id),
            now=datetime.now(UTC),
            authority_issuer=authority_issuer,
        )
        with self.database.connect_task_io() as connection:
            row = connection.execute(
                """SELECT o.diagnostics FROM agent_safety_overrides o
                JOIN execution_segments s ON s.deployment_namespace=o.deployment_namespace
                 AND s.session_id=o.session_id WHERE s.deployment_namespace=%s
                 AND s.task_id=%s AND o.reason=%s AND o.kind='watchdog' AND NOT o.shadow
                ORDER BY o.created_at LIMIT 1""",
                (self.database.deployment_namespace, task_id, STOP_REASON),
            ).fetchone()
        if row is None:
            return {
                "task_id": str(task_id),
                "stop_id": None,
                "request_accepted": False,
                "state": "not_requested",
                "resources_released": False,
                "execution": "unconfirmed",
                "lease": "unconfirmed",
                "sandbox": "pending",
                "synchronization": "pending",
                "error_code": None,
            }
        data = json.loads(row["diagnostics"])
        if data["task_id"] != str(task_id):
            raise ValueError("force stop scope changed")
        return self.public(data)

    def acknowledge_executor(self, sid: UUID, fence: Any) -> None:
        from agent_storage.postgres.force_stop_executors import acknowledge_executor

        acknowledge_executor(self.database, sid, fence)

    @staticmethod
    def public(data: dict[str, Any]) -> dict[str, Any]:
        execution = data.get("execution", "unconfirmed")
        lease = data.get("lease", "unconfirmed")
        sandbox = data.get("sandbox", "pending")
        verified = (
            execution == "stopped"
            and lease == "revoked"
            and sandbox in {"cleaned", "not_required"}
            and data.get("synchronization") == "synchronized"
        )
        phase = data.get("phase", "requested")
        state = (
            "stopped"
            if verified and phase == "done"
            else "requires_reconciliation"
            if phase in {"done", "requires_reconciliation"}
            else "stopping"
            if phase == "stopping"
            else "requested"
        )
        return {
            "task_id": data["task_id"],
            "stop_id": data["operation_id"],
            "request_accepted": True,
            "state": state,
            "resources_released": state == "stopped",
            "execution": execution,
            "lease": lease,
            "sandbox": sandbox,
            "synchronization": data.get("synchronization", "pending"),
            "error_code": data.get("error_code"),
        }
