"""Explicit ERP chat/query generation; no workspace or Artifact authority."""

import hashlib
import os
from uuid import UUID

PREFIX = "erpnext://chat-readonly/v1/"
TOOLS = frozenset({"agent.plan", "agent.clarify", "erpnext.discover", "erpnext.read"})
READS = frozenset(
    {"get", "query", "query_page", "aggregate", "report_describe", "workflow_transitions"}
)
OUTPUT_BYTES = 8192


def enabled(namespace="erpnext"):
    value = os.environ.get("ZEBRA_ERPNEXT_CHAT_READONLY", "disabled")
    if value not in {"disabled", "enabled"}:
        raise ValueError("invalid ERP chat readonly mode")
    if value == "enabled" and (
        namespace != "erpnext"
        or os.environ.get("ZEBRA_ERPNEXT_WORKSPACE_CONTAINMENT") != "enabled"
        or os.environ.get("ZEBRA_ERPNEXT_FRESH_AUTHORITY") != "enabled"
        or os.environ.get("ZEBRA_ERPNEXT_PRIVATE_WORKSPACES", "disabled") != "disabled"
        or not os.environ.get("ZEBRA_ERPNEXT_CHAT_SITE")
    ):
        raise ValueError(
            "ERP chat requires fixed namespace, containment, Fresh and site; "
            "private runtime remains disabled"
        )
    return value == "enabled"


def allowed_tools():
    value = os.environ.get("ZEBRA_ERPNEXT_PRODUCTION_PLAN_PROPOSALS", "disabled")
    if value not in {"disabled", "enabled"}:
        raise ValueError("invalid Production Plan proposal mode")
    if value == "enabled" and not enabled():
        raise ValueError("Production Plan proposals require the bounded ERP chat mode")
    # Native propose prepares human approval; it never confirms a business write.
    return TOOLS | {"erpnext.propose"} if value == "enabled" else TOOLS


def require_binding(binding, instance, task_id):
    from agent_core.domain.task_bindings import TaskBindingSnapshot, task_bound_host_thread
    from agent_core.domain.workspace_control import WorkspaceSourceKind

    if not isinstance(binding, TaskBindingSnapshot):
        raise ValueError("typed ERP chat binding required")
    binding = TaskBindingSnapshot.model_validate(binding.model_dump(mode="json"))
    host = binding.host_capability
    context = host.host_context
    if (
        context is None
        or (host.authority_issuer, host.host_app_id, host.namespace_id)
        != ("https://erpnext.zebra.local", "erpnext", "erpnext")
        or str(binding.task_id) != task_id
    ):
        raise ValueError("ERP chat binding identity mismatch")
    thread = task_bound_host_thread(binding, task_id=task_id).resource_id
    refs = {
        kind: [r.resource_id for r in context.resource_refs if r.resource_type == kind]
        for kind in ("principal", "company", "run")
    }
    if any(len(values) != 1 or not values[0] for values in refs.values()):
        raise ValueError("ERP chat requires one principal/company/Run")
    expected = (
        "erp-u-"
        + hashlib.sha256(
            (
                os.environ["ZEBRA_ERPNEXT_CHAT_SITE"]
                + "\0"
                + refs["principal"][0]
                + "\0"
                + refs["company"][0]
            ).encode()
        ).hexdigest()[:40]
    )
    if (
        context.workspace_ref != expected
        or "erpnext.read" not in context.scopes
        or set(context.scopes) - {"agent.run", "erpnext.read"}
        or str(UUID(thread)) != thread
        or instance.deployment_namespace != "erpnext"
        or instance.owner_session_id not in {None, UUID(task_id)}
        or instance.source.kind is not WorkspaceSourceKind.HOST_REFERENCE
        or instance.source.locator != PREFIX + thread + "/" + expected
        or instance.source.pinned_revision is not None
        or instance.source.archive_artifact_uri is not None
        or instance.source.content_digest is not None
        or instance.volume_ref is not None
        or instance.state.value != "pending"
    ):
        raise ValueError("ERP chat source/principal/company mismatch")
    return binding


def require_generation(connection, store, session_id, workspace=None):
    from agent_core.domain.workspace_control import WorkspaceId
    from agent_storage.postgres.task_admission import read_session_task_binding
    from agent_storage.postgres.workspaces import get_workspace_in_transaction

    row = connection.execute(
        (
            "SELECT task.task_id FROM agent_tasks task JOIN execution_segment"
            "s segment ON segment.deployment_namespace=task.deployment_namesp"
            "ace AND segment.task_id=task.task_id WHERE task.deployment_names"
            "pace=%s AND segment.session_id=%s AND task.active_segment_id=seg"
            "ment.session_id"
        ),
        ("erpnext", session_id),
    ).fetchone()
    native = get_workspace_in_transaction(connection, "erpnext", session_id)
    if row is None or native is None or workspace is not None and native != workspace:
        raise ValueError("ERP chat active native Task/workspace required")
    prefix = "workspace://" if native.workspace_root.startswith("workspace://") else "workspace:/"
    wid = str(UUID(native.workspace_root.removeprefix(prefix)))
    if native.workspace_root != prefix + wid:
        raise ValueError("noncanonical ERP chat workspace reference")
    instance = store.get_in_transaction(connection, WorkspaceId(UUID(wid)))
    return require_binding(
        read_session_task_binding(connection, "erpnext", session_id), instance, str(row["task_id"])
    )


def candidate_sql(alias):
    if alias not in {"p", "session_projections"}:
        raise ValueError("fixed ERP chat projection alias required")
    # ponytail: SQL only selects new candidates; typed binding and Fresh revalidate
    # before command handling/lease. Full private runtime keeps its separate gate.
    return (
        " AND EXISTS (\n        SELECT 1 FROM execution_segments chat_segm"
        "ent JOIN agent_tasks chat_task\n        ON chat_task.deployment_n"
        "amespace=chat_segment.deployment_namespace\n        AND chat_task"
        ".task_id=chat_segment.task_id AND chat_task.active_segment_id=ch"
        "at_segment.session_id\n        JOIN workspace_projections chat_pr"
        "ojection ON chat_projection.deployment_namespace=chat_segment.de"
        "ployment_namespace\n        AND chat_projection.session_id=chat_s"
        "egment.session_id\n        JOIN workspace_control_instances chat_"
        "instance ON chat_instance.deployment_namespace=chat_segment.depl"
        "oyment_namespace\n        AND chat_projection.workspace_root IN ("
        "'workspace://' || chat_instance.workspace_id::text,\n            "
        "'workspace:/' || chat_instance.workspace_id::text)\n        WHERE"
        " chat_segment.deployment_namespace="
        f"{alias}"
        ".deployment_namespace\n        AND chat_segment.session_id="
        f"{alias}"
        ".session_id AND chat_instance.source_kind='host_reference'\n     "
        "   AND chat_instance.source_locator LIKE 'erpnext://chat-readonl"
        "y/v1/%%'\n        AND chat_instance.state='pending' AND chat_inst"
        "ance.volume_ref IS NULL\n    ) "
    )
