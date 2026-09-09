"""Configuration permission is additional to live, fenced Worker execution."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from agent_core.domain.host_authority import HostGrantScopeError
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.task_bindings import host_context_digest
from agent_security.extension_worker_authority import ExtensionWorkerAuthority
from agent_security.host_grant import HostGrantBindingError

from tests.agent_runtime import test_mcp_anonymous_execution as fixtures
from tests.worker.test_worker_mcp_catalog import worker_authority

protector = fixtures.protector


def setup(tmp_path, protector, scopes=("agent.run", "extensions.read", "extensions.manage")):
    callback = fixtures.anonymous(tmp_path, protector)
    tasks = callback.release.tasks
    ceiling = tasks.resolve_task_ceiling.return_value
    host = ceiling.binding.host_capability
    context = host.host_context.model_copy(update={"scopes": scopes})
    host = host.model_copy(update={"host_context": context,
                                   "grant_digest": host_context_digest(context)})
    tasks.resolve_task_ceiling.return_value = ceiling.model_copy(update={
        "binding": ceiling.binding.model_copy(update={"host_capability": host}),
    })
    evidence = worker_authority(callback)
    authority = ExtensionWorkerAuthority(
        session_id=callback.session_id,
        expected_scope=callback.release.snapshots.get.return_value.scope,
        fence=callback.fence, tasks=tasks, leases=callback.leases,
        fresh_authority=lambda: evidence,
    )
    return authority, evidence


@pytest.mark.parametrize("scopes,permission,allowed", [
    (("agent.run",), "extensions.read", False),
    (("agent.run",), "extensions.manage", False),
    (("agent.run", "extensions.read"), "extensions.read", True),
    (("agent.run", "extensions.read"), "extensions.manage", False),
    (("agent.run", "extensions.manage"), "extensions.manage", True),
])
def test_explicit_scope_is_required(tmp_path, protector, scopes, permission, allowed):
    authority, evidence = setup(tmp_path, protector, scopes)
    assert evidence.snapshot.granted_authorities == ("agent.execute",)
    if allowed:
        assert authority(permission) == authority.expected_scope
    else:
        with pytest.raises(HostGrantScopeError):
            authority(permission)


@pytest.mark.parametrize("field", ["principal_id", "workspace_id", "namespace_id"])
def test_other_expected_identity_rejected(tmp_path, protector, field):
    authority, _ = setup(tmp_path, protector)
    authority = replace(authority, expected_scope=authority.expected_scope.model_copy(
        update={field: "another-tenant"},
    ))
    with pytest.raises(HostGrantBindingError):
        authority("extensions.manage")


def test_expired_execution_evidence_rejected(tmp_path, protector):
    authority, evidence = setup(tmp_path, protector)
    old = datetime.now(UTC) - timedelta(minutes=10)
    expired = replace(evidence, snapshot=type(evidence.snapshot).model_validate(
        evidence.snapshot.model_dump(exclude={"snapshot_digest"}) | {
            "issued_at": old, "validated_at": old, "expires_at": old + timedelta(seconds=30),
        },
    ))
    authority = replace(authority, fresh_authority=lambda: expired)
    with pytest.raises(HostGrantBindingError):
        authority("extensions.manage")


@pytest.mark.parametrize("change", ["released", "stolen", "expired"])
def test_lease_loss_rejected_before_loading_authority(tmp_path, protector, change):
    authority, evidence = setup(tmp_path, protector)
    if change == "expired":
        lease = authority.leases.get(authority.session_id)
        authority = replace(authority, leases=Mock(get=Mock(return_value=lease.model_copy(
            update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
        ))))
    else:
        authority.leases.release(authority.session_id, fence=authority.fence)
        if change == "stolen":
            authority.leases.acquire(authority.session_id, owner_instance_id="other",
                                     ttl=timedelta(minutes=5))
    fresh = Mock(return_value=evidence)
    authority = replace(authority, fresh_authority=fresh)
    with pytest.raises(LeaseLostError):
        authority("extensions.manage")
    fresh.assert_not_called()


def test_frozen_principal_tampering_invalidates_digest(tmp_path, protector):
    authority, _ = setup(tmp_path, protector)
    ceiling = authority.tasks.resolve_task_ceiling.return_value
    host = ceiling.binding.host_capability
    context = host.host_context.model_copy(update={"workspace_ref": "other-workspace"})
    authority.tasks.resolve_task_ceiling.return_value = ceiling.model_copy(update={
        "binding": ceiling.binding.model_copy(update={
            "host_capability": host.model_copy(update={"host_context": context}),
        }),
    })
    with pytest.raises((HostGrantBindingError, ValueError)):
        authority("extensions.manage")
