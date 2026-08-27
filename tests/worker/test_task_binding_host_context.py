from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from agent_core.domain.task_bindings import host_context_digest
from agent_core.domain.tool_profiles import ToolProfile
from agent_security import parse_network_profile
from zebra_agent_api.session_binding import _build_binding_snapshot
from zebra_agent_worker.task_recovery import RecoveredTask, apply_bound_host_context


def _context() -> HostContextEnvelope:
    return HostContextEnvelope(
        grant_id="grant-2",
        host_app_id="trench",
        namespace_id="trench:user-1",
        workspace_ref="trench-workspace:user-1",
        resource_refs=(HostResourceRef(type="trench.source", id="source-1"),),
        scopes=("trench:source:read",),
        limits=HostTechnicalLimits(
            max_runtime_seconds=300,
            max_model_tokens=10_000,
            max_artifact_bytes=1_000_000,
        ),
        origin="https://trench.local",
        policy_version="trench-read-v1",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )


def _task(tmp_path) -> RecoveredTask:
    return RecoveredTask(
        title="Trench",
        user_input="continue",
        workspace_root=tmp_path,
        policy_profile="read-only",
        tool_profile=ToolProfile.GENERAL,
        network_profile=parse_network_profile("none"),
        mcp_allowlist=None,
        skill_components=None,
        history_session_ids=None,
        max_attempts=1,
        max_model_calls=None,
        max_tool_calls=None,
        attachments=(),
        runtime_evidence=(),
        host_context=None,
        definition_snapshot=None,
    )


def test_worker_uses_exact_context_from_latest_binding(tmp_path) -> None:
    context = _context()
    binding = _build_binding_snapshot(
        "11111111-1111-1111-1111-111111111111",
        host_context=context,
        definition_snapshot_digest="a" * 64,
    )

    assert apply_bound_host_context(_task(tmp_path), binding).host_context == context


def test_worker_rejects_context_digest_drift(tmp_path) -> None:
    context = _context()
    binding = _build_binding_snapshot(
        "11111111-1111-1111-1111-111111111111",
        host_context=context,
        definition_snapshot_digest="a" * 64,
    )
    drifted = binding.model_copy(
        update={
            "host_capability": binding.host_capability.model_copy(
                update={
                    "grant_digest": host_context_digest(
                        context.model_copy(update={"grant_id": "other"})
                    )
                }
            )
        }
    )

    with pytest.raises(ValueError, match="digest does not match"):
        apply_bound_host_context(_task(tmp_path), drifted)
