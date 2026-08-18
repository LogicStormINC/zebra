import json
import sqlite3
from datetime import datetime
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.session_handoff import WorkspaceBindingRevision
from agent_core.ports.session_handoff import HandoffSourceFacts

from agent_storage.session_handoff_rows import sha256_text


def read_source_facts(
    connection: sqlite3.Connection,
    session_id: SessionId,
    *,
    at: datetime,
) -> HandoffSourceFacts:
    if at.tzinfo is None:
        raise ValueError("handoff source-fact timestamp must be timezone-aware")
    workspace = connection.execute(
        "SELECT * FROM workspace_projections WHERE session_id = ?",
        (str(session_id),),
    ).fetchone()
    if workspace is None:
        raise ValueError("handoff source workspace is missing")
    stream_version = connection.execute(
        "SELECT COALESCE(MAX(sequence), -1) FROM session_events WHERE session_id = ?",
        (str(session_id),),
    ).fetchone()[0]
    lease = connection.execute(
        """
        SELECT control_plane_epoch, fencing_token, worker_id, acquired_at,
               expires_at, released_at
        FROM worker_leases WHERE session_id = ?
        """,
        (str(session_id),),
    ).fetchone()
    epoch_row = connection.execute(
        """
        SELECT epoch FROM control_plane_epochs WHERE deployment_namespace = 'local'
        """
    ).fetchone()
    lease_fence = None
    if (
        lease is not None
        and lease["control_plane_epoch"] is not None
        and lease["fencing_token"] >= 1
    ):
        lease_fence = LeaseFence(
            control_plane_epoch=UUID(lease["control_plane_epoch"]),
            fencing_token=lease["fencing_token"],
            owner_instance_id=lease["worker_id"],
        )
    released_at = (
        None
        if lease is None or lease["released_at"] is None
        else datetime.fromisoformat(lease["released_at"])
    )
    has_active_lease = (
        lease_fence is not None
        and epoch_row is not None
        and str(lease_fence.control_plane_epoch) == epoch_row["epoch"]
        and datetime.fromisoformat(lease["acquired_at"]) <= at
        and datetime.fromisoformat(lease["expires_at"]) > at
        and (released_at is None or released_at > at)
    )
    authority_payload = {
        "policy_profile": workspace["policy_profile"],
        "network_profile": workspace["network_profile"],
        "network_allowlist": json.loads(workspace["network_allowlist"]),
        "mcp_allowlist": (
            None if workspace["mcp_allowlist"] is None else json.loads(workspace["mcp_allowlist"])
        ),
        "skill_components": (
            None
            if workspace["skill_components"] is None
            else json.loads(workspace["skill_components"])
        ),
    }
    workspace_payload = {
        "workspace_root": workspace["workspace_root"],
        "runtime_name": workspace["runtime_name"],
        "runtime_engine": workspace["runtime_engine"],
        "runtime_image": workspace["runtime_image"],
        "runtime_spec_digest": workspace["runtime_spec_digest"],
        "snapshot_id": workspace["snapshot_id"],
    }
    task_payload = {"tool_profile": workspace["tool_profile"]}
    return HandoffSourceFacts(
        stream_version=stream_version,
        lease_fence=lease_fence,
        has_active_lease=has_active_lease,
        authority_revision=_hash(authority_payload),
        workspace_revision=WorkspaceBindingRevision(
            workspace_id=workspace["workspace_root"],
            revision_hash=_hash(workspace_payload),
            runtime_snapshot_id=workspace["snapshot_id"],
        ),
        task_profile_revision=_hash(task_payload),
    )


def _hash(value: object) -> str:
    return sha256_text(json.dumps(value, sort_keys=True, separators=(",", ":")))
