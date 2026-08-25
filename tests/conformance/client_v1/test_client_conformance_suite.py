"""Shared client V1 conformance suite over two vocabulary-distinct frontends.

The same suite drives both fixtures; the platform code under test never
sees a business name — only published profile content (Gate 6).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from agent_core.domain.client_capabilities import (
    FrontendCapabilityProfileVersion,
    MountedCapabilitySnapshot,
)
from agent_core.domain.client_effects import (
    ClientEffectReceipt,
    ClientEffectStatus,
)
from agent_core.domain.client_sessions import (
    ClientSession,
    ClientSessionGrant,
)
from agent_core.domain.identifiers import (
    new_task_id,
    new_tool_call_id,
)
from agent_core.ports.platform_control_plane import AgentPlatformControlPlane

from tests.api.test_client_runtime_api import (
    FakeCapabilityRegistry,
    FakeControlLeaseStore,
    FakeSessionRegistry,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "conformance"


def _load_profile(frontend: str) -> FrontendCapabilityProfileVersion:
    import json

    payload = json.loads((FIXTURES / f"{frontend}_frontend_profile.json").read_text())
    return FrontendCapabilityProfileVersion.model_validate(
        {**payload, "published_at": datetime(2026, 8, 25, tzinfo=UTC)}
    )


@pytest.mark.parametrize("frontend", ["fake-frontend-a", "fake-frontend-b"])
def test_publish_mount_bind_schedule_receipt_chain(frontend: str) -> None:
    profile = _load_profile(frontend)
    action_name = next(iter(profile.action_names()))
    registry = FakeCapabilityRegistry()
    registry.publish_profile(profile)
    sessions = FakeSessionRegistry()
    leases = FakeControlLeaseStore()
    AgentPlatformControlPlane(
        deployment_namespace="conformance",
        frontend_capabilities=registry,
        client_sessions=sessions,
        client_control_leases=leases,
    )

    grant = ClientSessionGrant.model_validate(
        {
            "grant_id": uuid4(),
            "host_app_id": f"{frontend}-host",
            "namespace_id": "tenant-1",
            "frontend_app_id": profile.frontend_app_id,
            "origin": f"https://{frontend}.example",
            "user_ref": "user-1",
            "profile_digest": profile.profile_digest,
            "scopes": ["client.action"],
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        }
    )
    session = ClientSession(
        grant=grant,
        credential_hash="d" * 64,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    sessions.create_session(session)
    snapshot = MountedCapabilitySnapshot(
        client_session_id=session.session_id,
        frontend_app_id=profile.frontend_app_id,
        profile_revision=profile.revision,
        profile_digest=profile.profile_digest,
        mounted_actions=(action_name,),
        ui_revision=1,
        mounted_at=datetime.now(UTC),
    )
    snapshot.ensure_subset_of(profile)
    sessions.save_mounted_snapshot(snapshot)
    task_id = new_task_id()
    admission = (
        __import__("agent_control_plane.client_admission", fromlist=["ClientBindingService"])
        .ClientBindingService(sessions, leases)
        .bind_run(
            task_id=task_id,
            run_id="run-1",
            session_id=session.session_id,
            task_capability_scope=(action_name,),
        )
    )
    binding = admission.binding
    assert binding.allowed_actions == (action_name,)
    assert admission.lease is not None
    assert admission.controller_fence is not None

    from agent_control_plane.client_effects import (
        build_client_effect_request,
    )

    request = build_client_effect_request(
        binding=binding,
        tool_call_id=new_tool_call_id(),
        action_name=action_name,
        arguments={},
        action_contract_digest="a" * 64,
        fence_hash=admission.controller_fence.fence_hash,
        expected_ui_revision=1,
        session_id=task_id,
    )
    assert request.status is ClientEffectStatus.PENDING
    receipt = ClientEffectReceipt.model_validate(
        {
            "receipt_id": uuid4(),
            "effect_id": request.effect_id,
            "idempotency_key": request.idempotency_key,
            "request_digest": request.request_digest,
            "status": "succeeded",
            "result": {"ok": True},
            "received_at": datetime.now(UTC).isoformat(),
        }
    )
    assert receipt.matches(request)


def test_business_write_actions_never_publish() -> None:
    for frontend in ("fake-frontend-a", "fake-frontend-b"):
        profile = _load_profile(frontend)
        assert all(action.risk.value != "business_write_forbidden" for action in profile.actions)
