import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from agent_core.domain.identifiers import SessionId
from agent_core.domain.session_handoff import DEFAULT_MAX_HANDOFF_STAGE, WorkspaceBindingRevision

from agent_storage.session_handoff_rows import sha256_text


@dataclass(frozen=True, slots=True)
class HandoffSourceFacts:
    stream_version: int
    lease_fencing_token: int | None
    has_active_lease: bool
    authority_revision: str
    workspace_revision: WorkspaceBindingRevision
    task_profile_revision: str
    effective_depth_limit: int = DEFAULT_MAX_HANDOFF_STAGE


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
        "SELECT checkpoint, expires_at FROM worker_leases WHERE session_id = ?",
        (str(session_id),),
    ).fetchone()
    authority_payload = {
        "policy_profile": workspace["policy_profile"],
        "network_profile": workspace["network_profile"],
        "network_allowlist": json.loads(workspace["network_allowlist"]),
        "mcp_allowlist": (
            None if workspace["mcp_allowlist"] is None else json.loads(workspace["mcp_allowlist"])
        ),
        "preapproved_readonly_tools": (
            None
            if workspace["preapproved_readonly_tools"] is None
            else json.loads(workspace["preapproved_readonly_tools"])
        ),
        "skill_components": (
            None
            if workspace["skill_components"] is None
            else json.loads(workspace["skill_components"])
        ),
        **(
            {
                "skill_component_identities": json.loads(
                    workspace["skill_component_identities"]
                )
            }
            if workspace["skill_component_identities"] is not None
            else {}
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
    task_payload = {
        "tool_profile": workspace["tool_profile"],
        "agent_definition": (
            None
            if workspace["agent_definition"] is None
            else json.loads(workspace["agent_definition"])
        ),
    }
    return HandoffSourceFacts(
        stream_version=stream_version,
        lease_fencing_token=None if lease is None else lease["checkpoint"],
        has_active_lease=(lease is not None and datetime.fromisoformat(lease["expires_at"]) > at),
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
