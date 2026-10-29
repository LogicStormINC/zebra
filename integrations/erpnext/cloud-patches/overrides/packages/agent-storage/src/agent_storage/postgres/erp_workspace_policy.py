"""ERP source-generation containment; classification never grants execution authority."""

import os
import re
from typing import Any
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_core.domain.task_bindings import task_bound_host_thread
from agent_core.domain.workspace_control import WorkspaceId, WorkspaceSourceKind
from agent_storage.postgres.database import PostgresDatabase

ERP_CONTAINMENT_ENV = "ZEBRA_ERPNEXT_WORKSPACE_CONTAINMENT"
LEGACY_OBSERVATION_ONLY = "legacy_observation_only"
PRIVATE_NOT_ACTIVATED = "private_workspace_not_activated"


class ERPWorkspacePolicyRefusal(ValueError):
    """Policy refusal, deliberately unrelated to Worker setup/Attempt failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def containment_enabled(namespace: str | None) -> bool:
    value = os.environ.get(ERP_CONTAINMENT_ENV, "disabled")
    if value not in {"disabled", "enabled"}:
        raise ValueError("ERP containment must be disabled or enabled")
    if value == "enabled" and namespace != "erpnext":
        raise ValueError("ERP containment requires the erpnext deployment namespace")
    return value == "enabled"


def is_private_generation(binding: Any, instance: Any, *, task_id: str) -> bool:
    """Classify source/binding shape; callers must separately prove native lineage.

    Native API admission leaves owner_session_id NULL. It is never positive
    ownership evidence; a contradictory non-NULL owner does invalidate the source.
    """
    if binding is None or instance is None:
        return False
    try:
        thread = task_bound_host_thread(binding, task_id=task_id)
        host = binding.host_capability
        context = host.host_context
        if context is None or (
            host.authority_issuer != "https://erpnext.zebra.local"
            or host.host_app_id != "erpnext" or host.namespace_id != "erpnext"
            or instance.deployment_namespace != "erpnext"
            or instance.owner_session_id not in {None, UUID(task_id)}
            or instance.source.kind is not WorkspaceSourceKind.HOST_REFERENCE
            or re.fullmatch(r"erp-u-[0-9a-f]{40}", context.workspace_ref) is None
            or str(UUID(thread.resource_id)) != thread.resource_id
        ):
            return False
        return instance.source.locator == (
            f"erpnext://private-workspace/v1/{thread.resource_id}/{context.workspace_ref}"
        )
    except (AttributeError, TypeError, ValueError):
        return False


def private_activation_enabled(namespace: str | None) -> bool:
    value = os.environ.get("ZEBRA_ERPNEXT_PRIVATE_WORKSPACES", "disabled")
    if value not in {"disabled", "enabled"}:
        raise ValueError("invalid ERP private workspace activation")
    if value == "enabled" and (namespace != "erpnext" or not containment_enabled(namespace)
            or os.environ.get("ZEBRA_ERPNEXT_FRESH_AUTHORITY") != "enabled"):
        raise ValueError("private activation requires ERP containment and fresh authority")
    return value == "enabled"


class ERPWorkspaceContainment:
    """Use the same native control store as the Cloud resolver, without provisioning."""

    def __init__(self, dsn: str, *, deployment_namespace: str, workspace_control: Any) -> None:
        if deployment_namespace != "erpnext" or workspace_control.deployment_namespace != deployment_namespace:
            raise ValueError("ERP containment requires the same erpnext control store")
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self._workspace_control = workspace_control

    def require(self, session_id: SessionId, *, workspace: Any = None) -> None:
        with self._database.connect_task_io() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            self.require_in_transaction(connection, session_id, workspace=workspace)

    def require_in_transaction(self, connection: Any, session_id: SessionId, *, workspace: Any = None) -> None:
        from agent_storage.postgres.task_admission import read_session_task_binding
        from agent_storage.postgres.workspaces import get_workspace_in_transaction

        namespace = self._database.deployment_namespace
        if private_activation_enabled(namespace):
            from agent_storage.postgres.erp_private_workspace import private_facts
            try:
                _, _, native = private_facts(connection, self._workspace_control, session_id)
                if workspace is not None and workspace != native:
                    raise ValueError("recovery workspace drift")
                return  # Admission only. Execution also needs fresh Host + physical resolver gate.
            except (TypeError, ValueError, AttributeError) as error:
                raise ERPWorkspacePolicyRefusal(LEGACY_OBSERVATION_ONLY) from error
        code = LEGACY_OBSERVATION_ONLY
        try:
            row = connection.execute(
                "SELECT task.task_id FROM agent_tasks task JOIN execution_segments segment "
                "ON segment.deployment_namespace=task.deployment_namespace AND segment.task_id=task.task_id "
                "WHERE task.deployment_namespace=%s AND segment.session_id=%s "
                "AND task.active_segment_id=segment.session_id",
                (namespace, session_id),
            ).fetchone()
            native = get_workspace_in_transaction(connection, namespace, session_id)
            if row is not None and native is not None and (workspace is None or workspace == native):
                reference = native.workspace_root
                prefix = "workspace://" if reference.startswith("workspace://") else "workspace:/"
                workspace_id = UUID(reference.removeprefix(prefix))
                # Match both native resolver spellings; Path folds the double slash.
                # UUID shorthand, percent escapes and suffixes remain invalid.
                if reference == prefix + str(workspace_id):
                    instance = self._workspace_control.get_in_transaction(connection, WorkspaceId(workspace_id))
                    binding = read_session_task_binding(connection, namespace, session_id)
                    if is_private_generation(binding, instance, task_id=str(row["task_id"])):
                        code = PRIVATE_NOT_ACTIVATED
        except (TypeError, ValueError, AttributeError):
            pass  # Malformed historical ownership stays observation-only.
        # ponytail: no private generation is executable until real quota/mount and
        # fresh-authority hooks replace this refusal; a feature flag cannot do so.
        raise ERPWorkspacePolicyRefusal(code)


def containment_for_database(dsn: str, namespace: str) -> ERPWorkspaceContainment | None:
    if not containment_enabled(namespace):
        return None
    from agent_storage.postgres.workspace_control import PostgresWorkspaceControlStore

    return ERPWorkspaceContainment(
        dsn, deployment_namespace=namespace,
        workspace_control=PostgresWorkspaceControlStore(dsn, deployment_namespace=namespace),
    )


def eligible_execution_sql(namespace: str | None, *, alias: str = "session_projections") -> str:
    if not containment_enabled(namespace):
        return ""
    if not private_activation_enabled(namespace):
        return " AND FALSE "
    if alias not in {"p", "session_projections"}:
        raise ValueError("fixed projection alias required")
    # Filter before LIMIT to keep preserved legacy queues from starving new Tasks.
    # This is candidate selection, never binding or execution authorization.
    return f""" AND EXISTS (
        SELECT 1 FROM execution_segments private_segment
        JOIN agent_tasks private_task
          ON private_task.deployment_namespace=private_segment.deployment_namespace
         AND private_task.task_id=private_segment.task_id
         AND private_task.active_segment_id=private_segment.session_id
        JOIN workspace_projections private_projection
          ON private_projection.deployment_namespace=private_segment.deployment_namespace
         AND private_projection.session_id=private_segment.session_id
        JOIN workspace_control_instances private_instance
          ON private_instance.deployment_namespace=private_segment.deployment_namespace
         AND private_projection.workspace_root IN (
             'workspace://' || private_instance.workspace_id::text,
             'workspace:/' || private_instance.workspace_id::text)
        WHERE private_segment.deployment_namespace={alias}.deployment_namespace
          AND private_segment.session_id={alias}.session_id
          AND private_instance.source_kind='host_reference'
          AND private_instance.source_locator LIKE 'erpnext://private-workspace/v1/%%'
          AND private_instance.quota_bytes=268435456
          AND private_instance.state IN ('pending','ready','sealed')
    ) """
