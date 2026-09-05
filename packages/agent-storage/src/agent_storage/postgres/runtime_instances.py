"""Exact instance accounting; engine IO and cleanup scheduling live elsewhere."""

from collections.abc import Mapping
from datetime import datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from agent_core.application.execution_authority_replay import latest_authority_snapshot
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import SessionEvent
from agent_core.domain.execution_authority import ExecutionAuthorityDecision
from agent_core.domain.leases import WorkerLease
from agent_core.domain.task_bindings import TaskBindingSnapshot

from agent_storage.postgres.command_wakeup import _scope_from_binding
from agent_storage.postgres.command_wakeup_discovery import _database
from agent_storage.postgres.command_wakeup_handoff import _terminal_session
from agent_storage.postgres.leases import assert_current_lease_fence, lock_session_lease_boundary


class PostgresRuntimeInstances:
    """Bound to one trusted scope/full fence and one pinned engine configuration."""

    def __init__(
        self,
        dsn: str,
        *,
        deployment_namespace: str,
        scope: OpaqueAuthorityScope,
        lease: WorkerLease,
        engine_identity: str,
        workspace_ref: str | None = None,
    ) -> None:
        if not isinstance(scope, OpaqueAuthorityScope) or not isinstance(lease, WorkerLease):
            raise ValueError("runtime instances require trusted scope and full lease")
        if len(engine_identity) != 64 or any(c not in "0123456789abcdef" for c in engine_identity):
            raise ValueError("runtime engine identity must be a SHA256 fingerprint")
        self._database = _database(dsn, deployment_namespace)
        self._scope, self._lease = scope, lease
        self._workspace_ref = workspace_ref
        self._scope_key = sha256(scope.model_dump_json().encode()).hexdigest()
        self.engine_identity = engine_identity

    def reserve(self, instance_id: str, session_id: str, spec_digest: str) -> Mapping[str, str]:
        UUID(instance_id)
        if session_id != str(self._lease.session_id) or not spec_digest:
            raise ValueError("runtime instance does not match its authority")
        namespace = self._database.deployment_namespace
        fence = self._lease.fence
        with self._database.connect() as connection:
            self._authorize(connection)
            connection.execute(
                """INSERT INTO runtime_instances (
                  deployment_namespace,instance_id,session_id,tenant_id,workspace_id,scope_key,
                  control_plane_epoch,fencing_token,owner_instance_id,spec_digest,
                  engine_identity,container_name,authority_issuer)
                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    namespace,
                    instance_id,
                    self._lease.session_id,
                    self._scope.namespace_id,
                    self._workspace_ref,
                    self._scope_key,
                    fence.control_plane_epoch,
                    fence.fencing_token,
                    fence.owner_instance_id,
                    spec_digest,
                    self.engine_identity,
                    f"zebra-{instance_id}",
                    self._scope.authority_issuer,
                ),
            )
        return {
            "zebra.agent.instance": instance_id,
            "zebra.agent.namespace": namespace,
            "zebra.agent.scope": self._scope_key,
            "zebra.agent.epoch": str(fence.control_plane_epoch),
            "zebra.agent.fence": str(fence.fencing_token),
            "zebra.agent.engine": self.engine_identity,
        }

    def created(self, instance_id: str, container_id: str) -> None:
        """Record a late create even after revocation; this does not authorize start."""
        if len(container_id) != 64 or any(c not in "0123456789abcdef" for c in container_id):
            raise ValueError("invalid exact container identity")
        with self._database.connect() as connection:
            row = self._instance(connection, instance_id)
            if row["status"] == "removed" or row["container_id"] not in (None, container_id):
                raise ValueError("runtime instance identity conflicts")
            connection.execute(
                """UPDATE runtime_instances SET container_id=%s,status='created'
                   WHERE deployment_namespace=%s AND instance_id=%s""",
                (container_id, self._database.deployment_namespace, instance_id),
            )

    def authorize(self, instance_id: str, container_id: str) -> None:
        with self._database.connect() as connection:
            expires_at = self._authorize(connection)
            row = self._instance(connection, instance_id)
            if row["status"] != "created" or row["container_id"] != container_id:
                raise ValueError("runtime instance is not authorized to run")
            # All upstream locks are already held: this reacquires no new lock
            # order while accounting for an unchanged instance-row lock wait.
            assert_current_lease_fence(
                connection,
                self._database.deployment_namespace,
                self._lease.session_id,
                self._lease.fence,
            )
            clock = connection.execute("SELECT clock_timestamp() AS now").fetchone()
            assert clock is not None
            if expires_at <= clock["now"]:
                raise ValueError("runtime requires current canonical execution authority")

    def removed(self, instance_id: str, container_id: str) -> None:
        """Only a recorded exact ID with successful engine deletion may settle."""
        with self._database.connect() as connection:
            row = self._instance(connection, instance_id)
            if row["container_id"] != container_id or row["status"] == "provisioning":
                raise ValueError("unsettled runtime creation cannot be marked removed")
            connection.execute(
                """UPDATE runtime_instances SET status='removed',removed_at=clock_timestamp()
                   WHERE deployment_namespace=%s AND instance_id=%s""",
                (self._database.deployment_namespace, instance_id),
            )

    def _instance(self, connection: Any, instance_id: str) -> dict[str, Any]:
        UUID(instance_id)
        row = connection.execute(
            """SELECT * FROM runtime_instances WHERE deployment_namespace=%s AND instance_id=%s
               FOR UPDATE""",
            (self._database.deployment_namespace, instance_id),
        ).fetchone()
        fence = self._lease.fence
        if row is None or (
            row["session_id"],
            row["tenant_id"],
            row["workspace_id"],
            row["scope_key"],
            row["control_plane_epoch"],
            row["fencing_token"],
            row["owner_instance_id"],
            row["engine_identity"],
        ) != (
            self._lease.session_id,
            self._scope.namespace_id,
            self._workspace_ref,
            self._scope_key,
            fence.control_plane_epoch,
            fence.fencing_token,
            fence.owner_instance_id,
            self.engine_identity,
        ):
            raise ValueError("runtime instance authority conflicts")
        return dict(row)

    def _authorize(self, connection: Any) -> datetime:
        namespace, session_id = self._database.deployment_namespace, self._lease.session_id
        lock_session_lease_boundary(connection, namespace, session_id)
        assert_current_lease_fence(connection, namespace, session_id, self._lease.fence)
        stream = connection.execute(
            """SELECT current_version FROM session_streams
               WHERE deployment_namespace=%s AND session_id=%s FOR SHARE""",
            (namespace, session_id),
        ).fetchone()
        if stream is None:
            raise ValueError("runtime requires a canonical Session stream")
        assert_current_lease_fence(connection, namespace, session_id, self._lease.fence)
        rows = connection.execute(
            """SELECT * FROM session_events WHERE deployment_namespace=%s AND session_id=%s
               ORDER BY sequence""",
            (namespace, session_id),
        ).fetchall()
        if not rows or _terminal_session(connection, namespace, session_id):
            raise ValueError("runtime requires a nonterminal canonical Session")
        # ponytail: reuse the exact worker replay over full history; a bounded authority
        # projection can replace this O(history) read without changing security semantics.
        events = [SessionEvent.model_validate(row) for row in rows]
        authority = latest_authority_snapshot(events)
        now = connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        if (
            authority is None
            or authority.scope != self._scope
            or authority.expires_at <= now
            or authority.resolution
            not in (ExecutionAuthorityDecision.ALLOWED, ExecutionAuthorityDecision.NARROWED)
            or "agent.execute" not in authority.granted_authorities
            or not self._scope.allows_session(session_id)
        ):
            raise ValueError("runtime requires current canonical execution authority")
        session = connection.execute(
            """SELECT namespace_id FROM session_projections
               WHERE deployment_namespace=%s AND session_id=%s""",
            (namespace, session_id),
        ).fetchone()
        if session is None or session["namespace_id"] not in (None, self._scope.namespace_id):
            raise ValueError("runtime Session tenant conflicts with execution authority")
        binding_row = connection.execute(
            """SELECT binding.snapshot_json, binding.binding_digest, segment.task_id
               FROM execution_segments segment JOIN task_binding_snapshots binding
                 ON binding.deployment_namespace=segment.deployment_namespace
                AND binding.task_id=segment.task_id
               WHERE segment.deployment_namespace=%s AND segment.session_id=%s
               ORDER BY binding.binding_revision DESC LIMIT 1""",
            (namespace, session_id),
        ).fetchone()
        bound_workspace = None
        if binding_row is not None:
            binding = TaskBindingSnapshot.model_validate(binding_row["snapshot_json"])
            host = binding.host_capability
            if (
                binding.task_id != str(binding_row["task_id"])
                or binding.binding_digest != binding_row["binding_digest"]
                or (host.authority_issuer, host.namespace_id) != self._scope.scope_key
            ):
                raise ValueError("runtime frozen binding authority conflicts")
            if host.host_context is not None:
                bound_workspace = host.host_context.workspace_ref
        if bound_workspace != self._workspace_ref:
            raise ValueError("runtime frozen workspace identity conflicts")
        if bound_workspace is not None:
            scope = _scope_from_binding(connection, namespace, events[-1])
            if (scope.tenant_id, scope.workspace_id) != (
                self._scope.namespace_id,
                self._workspace_ref,
            ):
                raise ValueError("runtime requires matching frozen binding workspace")
        return authority.expires_at
