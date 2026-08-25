from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_core.domain.client_sessions import (
    ClientControlFence,
    ClientControlLease,
    ClientControllerRole,
    ClientGrantError,
    ClientSession,
    ClientSessionExpiredError,
    ClientSessionGrant,
    ClientSessionStatus,
    ensure_controller_handoff,
)
from agent_core.domain.identifiers import new_client_session_id
from pydantic import ValidationError

NOW = datetime.now(UTC)


def _grant(**overrides) -> ClientSessionGrant:
    payload = {
        "grant_id": uuid4(),
        "host_app_id": "trench",
        "namespace_id": "trn-tenant-1",
        "frontend_app_id": "trench-web",
        "origin": "https://app.trench.example",
        "user_ref": "user-42",
        "profile_digest": "a" * 64,
        "scopes": ("client.action",),
        "expires_at": NOW + timedelta(hours=1),
    }
    payload.update(overrides)
    return ClientSessionGrant.model_validate(payload)


def _session(**overrides) -> ClientSession:
    grant = overrides.pop("grant", None) or _grant()
    payload = {
        "grant": grant,
        "credential_hash": "d" * 64,
        "created_at": NOW,
        "expires_at": NOW + timedelta(hours=1),
    }
    payload.update(overrides)
    return ClientSession.model_validate(payload)


def test_grant_binds_host_namespace_frontend_and_origin() -> None:
    grant = _grant()
    grant.ensure_matches(
        host_app_id="trench",
        namespace_id="trn-tenant-1",
        frontend_app_id="trench-web",
        origin="https://app.trench.example/",
    )
    with pytest.raises(ClientGrantError):
        grant.ensure_matches(
            host_app_id="other",
            namespace_id="trn-tenant-1",
            frontend_app_id="trench-web",
            origin="https://app.trench.example",
        )


def test_grant_origin_must_be_bare_https() -> None:
    with pytest.raises(ValueError):
        _grant(origin="https://app.trench.example/path")


def test_grant_scopes_are_client_only() -> None:
    with pytest.raises(ValidationError) as info:
        _grant(scopes=("agent.run",))
    causes = [error.get("ctx", {}).get("error") for error in info.value.errors()]
    assert any(isinstance(cause, ClientGrantError) for cause in causes)


def test_fence_hash_never_exposes_the_token() -> None:
    fence = ClientControlFence.issue()
    dumped = fence.model_dump(mode="json")
    assert set(dumped) == {"token"}
    lease = ClientControlLease(
        run_binding_id=uuid4(),
        client_session_id=new_client_session_id(),
        fence_hash=fence.fence_hash,
        acquired_at=NOW,
        heartbeat_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    persisted = lease.model_dump(mode="json")
    assert fence.token not in str(persisted)
    assert lease.matches_fence(fence)


def test_expired_session_cannot_renew() -> None:
    expired = _session(status=ClientSessionStatus.EXPIRED)
    with pytest.raises(ClientSessionExpiredError):
        expired.ensure_renewable(now=NOW)


def test_active_session_can_renew() -> None:
    _session().ensure_renewable(now=NOW)


def test_observer_cannot_act_as_controller() -> None:
    lease = ClientControlLease(
        run_binding_id=uuid4(),
        client_session_id=new_client_session_id(),
        role=ClientControllerRole.OBSERVER,
        fence_hash="b" * 64,
        acquired_at=NOW,
        heartbeat_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    from agent_core.domain.client_sessions import ClientObserverActionError

    with pytest.raises(ClientObserverActionError):
        lease.require_controller()


def test_only_one_tab_claims_the_active_controller_lease() -> None:
    from agent_core.domain.client_sessions import ClientControlLeaseError

    holder_session = new_client_session_id()
    active = ClientControlLease(
        run_binding_id=uuid4(),
        client_session_id=holder_session,
        fence_hash="c" * 64,
        acquired_at=NOW,
        heartbeat_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    with pytest.raises(ClientControlLeaseError):
        ensure_controller_handoff(active, claimant_session_id=new_client_session_id())
    ensure_controller_handoff(active, claimant_session_id=holder_session)
    stale = active.model_copy(update={"expires_at": NOW - timedelta(seconds=1)})
    ensure_controller_handoff(stale, claimant_session_id=new_client_session_id())
