"""Bounded, immutable delegation ownership for whole-Task stop targets."""

from typing import Any
from uuid import UUID

from agent_core.domain.host_authority import HostContextEnvelope, HostResourceRef
from agent_core.domain.identifiers import TaskId
from agent_core.domain.task_bindings import TaskBindingSnapshot, require_task_host_context

from agent_storage.postgres.database import PostgresDatabase


# ponytail: stop at 64 delegated Tasks / 256 live segments, never silently certify
# a partial tree. Larger fleets need a persisted paginated stop frontier.
def stop_targets(database: PostgresDatabase, data: dict[str, Any]) -> list[dict[str, Any]]:
    namespace = database.deployment_namespace
    pending = [(UUID(data["task_id"]), data["binding_digest"], 0)]
    visited, targets = set(), []
    root_context = HostContextEnvelope.model_validate(data["context"])
    with database.connect_task_io() as connection:
        connection.execute("SET LOCAL statement_timeout='1500ms'")
        while pending:
            task, expected, depth = pending.pop()
            if task in visited:
                raise ValueError("delegation_cycle")
            visited.add(task)
            if len(visited) > 64 or depth > 32:
                raise ValueError("stop_target_budget_exceeded")
            row = connection.execute(
                """SELECT binding_digest,snapshot_json FROM task_binding_snapshots
                WHERE deployment_namespace=%s AND task_id=%s AND binding_digest=%s
                ORDER BY binding_revision DESC LIMIT 1""",
                (namespace, task, expected),
            ).fetchone()
            if row is None or row["binding_digest"] != expected:
                raise ValueError("stop_binding_changed")
            binding = TaskBindingSnapshot.model_validate(row["snapshot_json"])
            context = binding.host_capability.host_context
            if binding.binding_digest != expected or context is None:
                raise ValueError("stop_binding_changed")
            identity = ("host_app_id", "namespace_id", "origin", "workspace_ref")

            def principals(c: HostContextEnvelope) -> tuple[HostResourceRef, ...]:
                return tuple(r for r in c.resource_refs if r.resource_type == "principal")

            if (
                any(getattr(context, k) != getattr(root_context, k) for k in identity)
                or principals(context) != principals(root_context)
                or binding.host_capability.authority_issuer != data["authority_issuer"]
            ):
                raise ValueError("delegation_scope_conflict")
            # Validate the frozen identity at its own admission, not expired runtime authority.
            require_task_host_context(
                binding,
                context,
                task_id=str(task),
                now=binding.bound_at,
                authority_issuer=data["authority_issuer"],
            )
            segments = connection.execute(
                """SELECT s.session_id FROM execution_segments s JOIN agent_tasks t
                  ON t.deployment_namespace=s.deployment_namespace AND t.task_id=s.task_id
                WHERE s.deployment_namespace=%s AND s.task_id=%s AND
                (s.session_id=t.active_segment_id OR s.session_id=ANY(%s::uuid[])
                 OR EXISTS(SELECT 1 FROM worker_leases l
                  WHERE l.deployment_namespace=s.deployment_namespace AND l.session_id=s.session_id
                  AND l.released_at IS NULL) OR EXISTS(SELECT 1 FROM runtime_instances r
                  WHERE r.deployment_namespace=s.deployment_namespace AND r.session_id=s.session_id
                  AND r.status<>'removed')) ORDER BY s.session_id LIMIT 257""",
                (namespace, task, data.get("target_sessions", [])),
            ).fetchall()
            for segment in segments:
                targets.append({"session_id": segment["session_id"], "binding": binding})
            if len(targets) > 256:
                raise ValueError("stop_target_budget_exceeded")
            links = connection.execute(
                """SELECT parent_binding_digest,child_task_id,child_binding_digest
                FROM subagent_delegation_links WHERE deployment_namespace=%s
                  AND parent_task_id=%s AND child_task_id IS NOT NULL LIMIT 65""",
                (namespace, TaskId(task)),
            ).fetchall()
            for link in links:
                if not link["child_binding_digest"]:
                    raise ValueError("delegation_scope_conflict")
                if link["parent_binding_digest"] != expected:
                    old = connection.execute(
                        """SELECT snapshot_json FROM task_binding_snapshots
                        WHERE deployment_namespace=%s AND task_id=%s AND binding_digest=%s""",
                        (namespace, task, link["parent_binding_digest"]),
                    ).fetchone()
                    if old is None:
                        raise ValueError("delegation_scope_conflict")
                    prior = TaskBindingSnapshot.model_validate(old["snapshot_json"]).host_capability
                    if (
                        prior.host_context is None
                        or prior.authority_issuer != data["authority_issuer"]
                        or any(
                            getattr(prior.host_context, k) != getattr(context, k) for k in identity
                        )
                        or principals(prior.host_context) != principals(context)
                    ):
                        raise ValueError("delegation_scope_conflict")
                pending.append((link["child_task_id"], link["child_binding_digest"], depth + 1))
        if not targets:
            raise ValueError("stop_target_missing")
    return targets
