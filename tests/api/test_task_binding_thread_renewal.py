"""Renew only execution coordinates, never the immutable business authority."""

from datetime import UTC, datetime, timedelta

import pytest
from agent_core.domain.host_authority import HostResourceRef
from agent_security.host_grant import JwtAlgorithm, VerifiedHostGrant
from zebra_agent_api.session_binding import _build_binding_snapshot, renew_task_binding_snapshot

from tests.api.test_task_resource_binding import TASK, THREAD


def context():
    from agent_core.domain.host_authority import HostContextEnvelope

    return HostContextEnvelope(
        grant_id="fresh",
        host_app_id="trench",
        namespace_id="trench-prod",
        workspace_ref="workspace-a",
        resource_refs=(
            HostResourceRef(type="thread", id=THREAD),
            HostResourceRef(type="run", id="bootstrap"),
            HostResourceRef(type="principal", id="user-a"),
            HostResourceRef(type="trench.source", id="source-a"),
        ),
        scopes=("agent.run", "source.read"),
        limits={"max_runtime_seconds": 60, "max_model_tokens": 1000, "max_artifact_bytes": 1024},
        origin="https://trench.local",
        policy_version="v1",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )


def bound(original=None):
    original = original or context()
    return _build_binding_snapshot(
        TASK,
        host_context=original,
        definition_snapshot_digest="a" * 64,
        verified_host_grant=VerifiedHostGrant(
            original, original.grant_id, JwtAlgorithm.RS256, "https://broker.local", "user-a"
        ),
    )


def test_renewal_retains_thread_and_ceilings_with_a_new_run():
    original = context()
    binding = bound(original)
    fresh = original.model_copy(
        update={
            "grant_id": "next",
            "resource_refs": tuple(
                HostResourceRef(type="run", id="new-run") if ref.resource_type == "run" else ref
                for ref in original.resource_refs
            ),
        }
    )
    renewed = renew_task_binding_snapshot(binding, fresh, authority_issuer="https://broker.local")
    assert renewed.binding_revision == 2 and renewed.host_capability.host_context == fresh
    assert renewed.effective_capabilities == binding.effective_capabilities
    assert (
        renewed.host_capability.resource_binding_digest
        == binding.host_capability.resource_binding_digest
    )
    assert renewed.agent_capability_ceiling == binding.agent_capability_ceiling


@pytest.mark.parametrize(
    "kind", ["missing", "wrong", "uuid", "ambiguous", "principal", "run_ambiguous"]
)
def test_renewal_cannot_erase_or_change_target_identity(kind):
    original = context()
    refs = tuple(ref for ref in original.resource_refs if ref.resource_type != "thread")
    if kind == "wrong":
        refs += (HostResourceRef(type="thread", id="other"),)
    elif kind == "uuid":
        refs += (HostResourceRef(type="thread", id=TASK),)
    elif kind == "ambiguous":
        refs += (
            HostResourceRef(type="thread", id=THREAD),
            HostResourceRef(type="thread", id="other"),
        )
    elif kind == "principal":
        refs = tuple(ref for ref in original.resource_refs if ref.resource_type != "principal")
    elif kind == "run_ambiguous":
        refs = original.resource_refs + (HostResourceRef(type="run", id="other"),)
    with pytest.raises(ValueError):
        renew_task_binding_snapshot(
            bound(original), original.model_copy(update={"resource_refs": refs})
        )


@pytest.mark.parametrize(
    "change",
    [
        {"scopes": ("agent.run", "source.read", "source.write")},
        {"policy_version": "v2"},
        {
            "limits": {
                "max_runtime_seconds": 61,
                "max_model_tokens": 1000,
                "max_artifact_bytes": 1024,
            }
        },
        {"resource": HostResourceRef(type="trench.source", id="source-b")},
    ],
)
def test_business_ceilings_cannot_expand(change):
    original = context()
    data = original.model_dump()
    change = dict(change)
    if "resource" in change:
        data["resource_refs"] = original.resource_refs + (change.pop("resource"),)
    data.update(change)
    fresh = type(original).model_validate(data)
    with pytest.raises(ValueError):
        renew_task_binding_snapshot(bound(original), fresh)


def test_issuer_and_current_expiry_are_checked():
    original = context()
    binding = bound(original)
    with pytest.raises(ValueError, match="issuer"):
        renew_task_binding_snapshot(binding, original, authority_issuer="https://wrong.test")
    with pytest.raises(ValueError, match="expired"):
        renew_task_binding_snapshot(
            binding, original.model_copy(update={"expires_at": datetime.now(UTC)})
        )


def test_real_worker_renewal_with_stable_thread_after_original_expiry():
    from uuid import UUID

    from agent_core.domain.execution_authority import ExecutionAuthorityResolutionRequest
    from agent_core.domain.identifiers import SessionId
    from zebra_agent_worker.bound_execution_authority import BoundHostExecutionAuthorityResolver

    original = context()
    binding = bound(original)
    initial = BoundHostExecutionAuthorityResolver(binding)
    now = datetime.now(UTC)
    request = ExecutionAuthorityResolutionRequest(
        session_id=SessionId(UUID(TASK)),
        attempt_number=1,
        scope=initial.scope,
        validated_at=now,
    )
    prior = initial.resolve_for_attempt(request)
    later = original.expires_at + timedelta(seconds=1)
    fresh = original.model_copy(
        update={
            "grant_id": "next-run-renewal",
            "expires_at": later + timedelta(minutes=5),
            "resource_refs": tuple(
                HostResourceRef(type="run", id="next-run") if ref.resource_type == "run" else ref
                for ref in original.resource_refs
            ),
        }
    )
    renewed = renew_task_binding_snapshot(binding, fresh, bound_at=later)
    current = BoundHostExecutionAuthorityResolver(renewed)
    resolved = current.resolve_renewed_binding(
        request.model_copy(update={"validated_at": later}), prior
    )
    assert resolved is not None and resolved.expires_at > prior.expires_at
    assert resolved.scope == prior.scope
    assert set(resolved.granted_authorities).issubset(prior.granted_authorities)
    assert resolved.effective_limits.is_no_broader_than(prior.effective_limits)
