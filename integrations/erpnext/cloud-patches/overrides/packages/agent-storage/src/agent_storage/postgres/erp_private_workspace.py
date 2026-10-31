"""Native105 identity proof for the ERP-only root-owned quota operator."""

import hashlib
import json
from datetime import UTC, datetime
from time import monotonic
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_core.domain.task_bindings import task_bound_host_thread
from agent_core.domain.workspace_control import WorkspaceId
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.erp_workspace_policy import is_private_generation
from agent_storage.postgres.task_admission import read_session_task_binding
from agent_storage.postgres.workspace_control import PostgresWorkspaceControlStore
from agent_storage.postgres.workspaces import get_workspace_in_transaction

QUOTA_BYTES = 256 * 1024 * 1024


def reject_private_coverage(connection, namespace, session_id, accepted_id):
    from agent_storage.postgres.coverage_recovery_preparation import CoverageRecoveryDeferred

    row = connection.execute(
        # Native strict_command_source treats any raw Task-segment marker or
        # Task requirement as strict, without exporting the prepared input body.
        (
            "SELECT EXISTS(SELECT 1 FROM execution_segments target JOIN execu"
            "tion_segments source ON source.deployment_namespace=target.deplo"
            "yment_namespace AND source.task_id=target.task_id JOIN session_e"
            "vents marker ON marker.deployment_namespace=source.deployment_na"
            "mespace AND marker.session_id=source.session_id WHERE target.dep"
            "loyment_namespace=%s AND target.session_id=%s AND marker.event_t"
            "ype='task_prepared' AND marker.payload ? 'coverage_admission') O"
            "R EXISTS(SELECT 1 FROM command_coverage_requirements requirement"
            " JOIN execution_segments target ON target.deployment_namespace=r"
            "equirement.deployment_namespace AND target.task_id=requirement.t"
            "ask_id WHERE target.deployment_namespace=%s AND target.session_i"
            "d=%s) OR EXISTS(SELECT 1 FROM command_recovery_attempts WHERE de"
            "ployment_namespace=%s AND accepted_event_id=%s AND reason IN ('c"
            "overage_checkpoint','coverage_continuation')) AS blocked"
        ),
        (namespace, session_id, namespace, session_id, namespace, accepted_id),
    ).fetchone()
    if row is None or row["blocked"]:
        raise CoverageRecoveryDeferred("erp_fresh_coverage_not_activated")


def private_command_settlement(connection, namespace, scope, accepted_id, raw, scope_mode):
    """Only canonical, durable no-execution outcomes bypass cold authority work."""
    from agent_core.contracts.broker_envelope import parse_broker_envelope
    from agent_storage.postgres.command_rollout import command_scope_mode
    from agent_storage.postgres.command_wakeup import command_scope_key
    from agent_storage.postgres.command_wakeup_handoff import _check_inbox
    from agent_storage.postgres.command_wakeup_receipts import _validate

    pending = connection.execute(
        (
            "SELECT * FROM session_command_pending WHERE deployment_namespace"
            "=%s AND accepted_event_id=%s"
        ),
        (namespace, accepted_id),
    ).fetchone()
    if pending is None or (pending["scope_key"], pending["tenant_id"], pending["workspace_id"]) != (
        command_scope_key(scope),
        scope.tenant_id,
        scope.workspace_id,
    ):
        raise ValueError("private settlement canonical scope mismatch")
    generation = (
        pending["current_generation"] if raw is None else parse_broker_envelope(raw).wake_generation
    )
    outbox = connection.execute(
        (
            "SELECT * FROM broker_outbox WHERE deployment_namespace=%s AND sc"
            "ope_key=%s AND operation_id=%s AND wake_generation=%s AND messag"
            "e_type='zebra.session.command.ready'"
        ),
        (namespace, pending["scope_key"], pending["command_id"], generation),
    ).fetchone()
    if outbox is None:
        raise ValueError("private settlement canonical outbox missing")
    reject_private_coverage(connection, namespace, pending["session_id"], accepted_id)
    _validate(connection, namespace, pending, outbox, scope, raw, metadata_only=True)
    _check_inbox(connection, namespace, pending, outbox)
    if scope_mode is not None and (
        (command_scope_mode(connection, namespace, pending["scope_key"]) == "broker")
        != (scope_mode == "broker")
    ):
        return "scope_settled" if pending["status"] != "pending" else None
    if generation < pending["current_generation"]:
        return "duplicate"
    if generation != pending["current_generation"]:
        raise ValueError("private settlement generation not approved")
    retired = connection.execute(
        "SELECT 1 FROM command_retirements WHERE deployment_namespace=%s AND accepted_event_id=%s "
        "AND scope_key=%s AND session_id=%s AND command_id=%s",
        (
            namespace,
            accepted_id,
            pending["scope_key"],
            pending["session_id"],
            pending["command_id"],
        ),
    ).fetchone()
    if retired is not None:
        return "retired_noop"
    receipt = connection.execute(
        (
            "SELECT * FROM command_handoff_receipts WHERE deployment_namespac"
            "e=%s AND scope_key=%s AND command_id=%s"
        ),
        (namespace, pending["scope_key"], pending["command_id"]),
    ).fetchone()
    if receipt is not None:
        if (
            receipt["accepted_event_id"] != accepted_id
            or receipt["session_id"] != pending["session_id"]
        ):
            raise ValueError("private settlement canonical receipt identity conflict")
        if receipt["handled_event_id"] is not None:
            return "duplicate"
        if receipt["wake_generation"] == generation:
            return "duplicate" if receipt["status"] == "accepted" else "requires_reconciliation"
    return None


def private_facts(connection, store, session_id, workspace_id=None, *, metadata_only=False):
    namespace = "erpnext"
    row = connection.execute(
        (
            "SELECT task.task_id FROM agent_tasks task JOIN execution_segment"
            "s segment ON segment.deployment_namespace=task.deployment_namesp"
            "ace AND segment.task_id=task.task_id WHERE task.deployment_names"
            "pace=%s AND segment.session_id=%s AND task.active_segment_id=seg"
            "ment.session_id"
        ),
        (namespace, session_id),
    ).fetchone()
    if metadata_only:
        # ponytail: allocation proof reads only the locator; Worker containment keeps
        # full projection validation/equality below. Proof result three is None.
        workspace = None
        projection = connection.execute(
            "SELECT workspace_root FROM workspace_projections "
            "WHERE deployment_namespace=%s AND session_id=%s",
            (namespace, session_id),
        ).fetchone()
        if row is None or projection is None:
            raise ValueError("missing active native Task workspace")
        reference = projection["workspace_root"]
    else:
        workspace = get_workspace_in_transaction(connection, namespace, session_id)
        if row is None or workspace is None:
            raise ValueError("missing active native Task workspace")
        reference = workspace.workspace_root
    prefix = "workspace://" if reference.startswith("workspace://") else "workspace:/"
    wid = str(UUID(reference.removeprefix(prefix)))
    if reference != prefix + wid or workspace_id is not None and wid != workspace_id:
        raise ValueError("workspace projection mismatch")
    instance = store.get_in_transaction(connection, WorkspaceId(UUID(wid)))
    binding = read_session_task_binding(connection, namespace, session_id)
    if not is_private_generation(binding, instance, task_id=str(row["task_id"])):
        raise ValueError("workspace source is outside the private generation")
    context = binding.host_capability.host_context
    thread = task_bound_host_thread(binding, task_id=str(row["task_id"]))
    principals = [
        ref.resource_id for ref in context.resource_refs if ref.resource_type == "principal"
    ]
    runs = [ref.resource_id for ref in context.resource_refs if ref.resource_type == "run"]
    if (
        len(principals) != 1
        or len(runs) != 1
        or "erpnext.read" not in context.scopes
        or instance.quota_bytes != QUOTA_BYTES
        or instance.state.value not in {"pending", "ready", "sealed"}
        or instance.source.pinned_revision is not None
        or instance.source.archive_artifact_uri is not None
        or instance.source.content_digest is not None
    ):
        raise ValueError("native binding/source facts disagree")
    expected_path = "/var/lib/zebra/erpnext-private-workspaces/" + wid
    if instance.state.value in {"ready", "sealed"} and instance.volume_ref != expected_path:
        raise ValueError("private durable volume path mismatch")
    # Grant revision/Run/segment may legitimately rotate. Receipt identity retains
    # immutable Task/thread/principal/company-scoped Host workspace and UUID only.
    identity = hashlib.sha256(
        json.dumps(
            dict(
                task_id=str(row["task_id"]),
                thread=thread.resource_id,
                principal=principals[0],
                workspace_ref=context.workspace_ref,
                workspace_id=wid,
                source=instance.source.locator,
            ),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return identity, instance, workspace


def native_workspace_proof(dsn, session_id, workspace_id, *, shared_secret, ca_pem=None):
    import ssl

    import httpx
    from agent_integrations.host_credentials import ConfiguredHmacHostCredentialResolver
    from agent_storage.postgres.database import postgres_deadline
    from agent_storage.postgres.host_connectors import PostgresHostConnectorRegistry
    from zebra_agent_worker.erp_fresh_authority import FreshERPAuthority

    sid, wid = UUID(session_id), str(UUID(workspace_id))
    if str(sid) != session_id or wid != workspace_id:
        raise ValueError("canonical native identifiers required")
    database = PostgresDatabase(dsn, deployment_namespace="erpnext")
    store = PostgresWorkspaceControlStore(dsn, deployment_namespace="erpnext")
    deadline = monotonic() + 5
    with postgres_deadline(deadline):
        with database.connect_task_io(deadline=deadline) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            identity, instance, _ = private_facts(
                connection, store, SessionId(sid), wid, metadata_only=True
            )
            binding = read_session_task_binding(connection, "erpnext", SessionId(sid))
        with httpx.Client(
            verify=ssl.create_default_context(cadata=ca_pem), follow_redirects=False
        ) as client:
            fresh = FreshERPAuthority(
                binding,
                PostgresHostConnectorRegistry(dsn, deployment_namespace="erpnext"),
                ConfiguredHmacHostCredentialResolver(shared_secret),
                task_id=binding.task_id,
                client=client,
            )
            expires_at = fresh.probe(datetime.now(UTC)).require_allowed()
    return identity, instance.state.value, expires_at.timestamp()
