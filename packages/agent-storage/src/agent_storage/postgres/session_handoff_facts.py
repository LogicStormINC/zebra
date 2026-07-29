"""PostgreSQL source facts used by Handoff reservation and recovery."""

import hashlib
import json
from datetime import datetime
from typing import Any

from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.session_handoff import WorkspaceBindingRevision
from agent_core.ports.session_handoff import HandoffSourceFacts


def read_source_facts_in_transaction(
    connection: Any,
    deployment_namespace: str,
    session_id: SessionId,
    *,
    at: datetime,
    lock_workspace: bool = False,
) -> HandoffSourceFacts:
    if at.tzinfo is None:
        raise ValueError("handoff source-fact timestamp must be timezone-aware")
    workspace_query = """
        SELECT * FROM workspace_projections
        WHERE deployment_namespace = %s AND session_id = %s
    """
    if lock_workspace:
        workspace_query += " FOR SHARE"
    workspace = connection.execute(
        workspace_query,
        (deployment_namespace, session_id),
    ).fetchone()
    if workspace is None:
        raise ValueError("handoff source workspace is missing")
    stream = connection.execute(
        """
        SELECT current_version FROM session_streams
        WHERE deployment_namespace = %s AND session_id = %s
        """,
        (deployment_namespace, session_id),
    ).fetchone()
    if stream is None:
        raise ValueError("handoff source stream is missing")
    lease = connection.execute(
        """
        SELECT lease.*,
               lease.control_plane_epoch = authority.epoch
               AND lease.acquired_at <= transaction_timestamp()
               AND lease.expires_at > transaction_timestamp()
               AND lease.released_at IS NULL AS is_active
        FROM worker_leases lease
        LEFT JOIN control_plane_epochs authority
          ON authority.deployment_namespace = lease.deployment_namespace
        WHERE lease.deployment_namespace = %s AND lease.session_id = %s
        """,
        (deployment_namespace, session_id),
    ).fetchone()
    lease_fence = None if lease is None else LeaseFence(
        control_plane_epoch=lease["control_plane_epoch"],
        fencing_token=lease["fencing_token"],
        owner_instance_id=lease["owner_instance_id"],
    )
    return HandoffSourceFacts(
        stream_version=stream["current_version"],
        lease_fence=lease_fence,
        has_active_lease=bool(lease is not None and lease["is_active"]),
        authority_revision=_hash(
            {
                "policy_profile": workspace["policy_profile"],
                "network_profile": workspace["network_profile"],
                "network_allowlist": workspace["network_allowlist"],
                "mcp_allowlist": workspace["mcp_allowlist"],
                "skill_components": workspace["skill_components"],
            }
        ),
        workspace_revision=workspace_revision_from_row(workspace),
        task_profile_revision=_hash({"tool_profile": workspace["tool_profile"]}),
    )


def workspace_revision_from_row(workspace: dict[str, Any]) -> WorkspaceBindingRevision:
    return WorkspaceBindingRevision(
        workspace_id=workspace["workspace_root"],
        revision_hash=_hash(
            {
                "workspace_root": workspace["workspace_root"],
                "runtime_name": workspace["runtime_name"],
                "runtime_engine": workspace["runtime_engine"],
                "runtime_image": workspace["runtime_image"],
                "runtime_spec_digest": workspace["runtime_spec_digest"],
                "snapshot_id": workspace["snapshot_id"],
            }
        ),
        runtime_snapshot_id=workspace["snapshot_id"],
    )


def _hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
