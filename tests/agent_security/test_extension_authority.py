from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Literal, cast

import pytest
from agent_core.domain.host_authority import HostContextEnvelope, HostSessionGrant
from agent_security.extension_authority import (
    extension_runtime_scope_from_grant,
    extension_runtime_scope_from_task_grant,
    extension_scope_from_grant,
)
from agent_security.host_grant import (
    HostGrantBindingError,
    HostGrantVerificationConfig,
    HostGrantVerifier,
    JwtAlgorithm,
    VerifiedHostGrant,
)

Permission = Literal["extensions.read", "extensions.manage"]


def _verified(**overrides: object) -> VerifiedHostGrant:
    now = datetime(2026, 9, 6, tzinfo=UTC)
    claims: dict[str, object] = {
        "iss": "https://host.example.com",
        "aud": "zebra",
        "sub": "subject-a",
        "jti": "grant-a",
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(now.timestamp()) + 300,
        "host_app_id": "host",
        "namespace_id": "namespace-a",
        "workspace_ref": "workspace-a",
        "resource_refs": [
            {"type": "principal", "id": "subject-a"},
            {"type": "event", "id": "event-a"},
        ],
        "scopes": ["extensions.read", "extensions.manage"],
        "limits": {
            "max_runtime_seconds": 300,
            "max_model_tokens": 1000,
            "max_artifact_bytes": 1000,
        },
        "origin": "https://host.example.com",
        "policy_version": "v1",
    }
    claims.update(overrides)
    grant = HostSessionGrant.model_validate(claims)
    verifier = HostGrantVerifier(
        HostGrantVerificationConfig(
            issuer=grant.iss,
            audience=grant.aud,
            jwks_uri=f"{grant.iss}/jwks",
            allowed_origins=(grant.origin,),
        )
    )
    return verifier.verify(grant, algorithm=JwtAlgorithm.RS256, now=now)


@pytest.mark.parametrize(
    ("claim", "field", "value"),
    (
        ("iss", "authority_issuer", "https://other.example.com"),
        ("sub", "principal_id", "subject-b"),
        ("namespace_id", "namespace_id", "namespace-b"),
        ("workspace_ref", "workspace_id", "workspace-b"),
    ),
)
def test_each_verified_identity_changes_only_its_exact_scope_field(
    claim: str, field: str, value: str
) -> None:
    baseline = extension_scope_from_grant(_verified(), permission="extensions.read")
    assert baseline.model_dump() == {
        "authority_issuer": "https://host.example.com",
        "namespace_id": "namespace-a",
        "principal_id": "subject-a",
        "workspace_id": "workspace-a",
    }
    changed = extension_scope_from_grant(_verified(**{claim: value}), permission="extensions.read")
    assert changed != baseline
    assert changed.model_dump() == baseline.model_dump() | {field: value}


@pytest.mark.parametrize(
    ("scopes", "permission", "allowed"),
    (
        (["agent.run"], "extensions.read", False),
        (["agent.run"], "extensions.manage", False),
        (["extensions.read"], "extensions.read", True),
        (["extensions.read"], "extensions.manage", False),
        (["extensions.manage"], "extensions.read", False),
        (["extensions.manage"], "extensions.manage", True),
        (["extensions.read", "extensions.manage"], "extensions.read", True),
        (["extensions.read", "extensions.manage"], "extensions.manage", True),
    ),
)
def test_permission_requires_exact_grant(
    scopes: list[str], permission: Permission, allowed: bool
) -> None:
    verified = _verified(scopes=scopes)
    if allowed:
        assert extension_scope_from_grant(verified, permission=permission)
    else:
        with pytest.raises(HostGrantBindingError, match="authority or permission is invalid"):
            extension_scope_from_grant(verified, permission=permission)


def test_context_and_duck_typed_grants_cannot_supply_authority() -> None:
    verified = _verified()
    for untrusted in (
        verified.context,
        verified.context.model_dump(),
        SimpleNamespace(**vars(verified)),
        replace(verified, context=cast(HostContextEnvelope, SimpleNamespace())),
    ):
        with pytest.raises(HostGrantBindingError, match="requires a verified Host Grant"):
            extension_scope_from_grant(
                cast(VerifiedHostGrant, untrusted), permission="extensions.read"
            )


@pytest.mark.parametrize("permission", ("agent.run", "extensions.write", " extensions.read", ""))
def test_unsupported_permissions_fail_at_runtime(permission: str) -> None:
    with pytest.raises(HostGrantBindingError, match="permission is not supported"):
        extension_scope_from_grant(_verified(), permission=cast(Permission, permission))


@pytest.mark.parametrize(
    "field", ("authority_issuer", "subject_ref", "namespace_id", "workspace_ref")
)
@pytest.mark.parametrize("value", ("", " untrimmed", "private\x00identity"))
def test_invalid_identity_is_rejected_without_leaking_values(field: str, value: str) -> None:
    verified = _verified()
    if field in {"namespace_id", "workspace_ref"}:
        verified = replace(verified, context=verified.context.model_copy(update={field: value}))
    else:
        verified = replace(verified, **{field: value})
    with pytest.raises(HostGrantBindingError) as error:
        extension_scope_from_grant(verified, permission="extensions.read")
    assert str(error.value) == "Extension authority or permission is invalid"
    assert error.value.__suppress_context__


def test_runtime_scope_requires_agent_run_not_configuration_visibility() -> None:
    runtime = _verified(scopes=["agent.run"])
    assert extension_runtime_scope_from_grant(runtime).workspace_id == "workspace-a"

    for scopes in (["extensions.read"], ["extensions.manage"]):
        with pytest.raises(HostGrantBindingError, match="runtime authority is invalid"):
            extension_runtime_scope_from_grant(_verified(scopes=scopes))


def test_runtime_scope_rejects_duck_typed_grant() -> None:
    verified = _verified(scopes=["agent.run"])
    with pytest.raises(HostGrantBindingError, match="requires a verified Host Grant"):
        extension_runtime_scope_from_grant(
            cast(VerifiedHostGrant, SimpleNamespace(**vars(verified)))
        )


def _task_binding(verified: VerifiedHostGrant):
    from datetime import datetime

    from agent_core.domain.task_bindings import TaskBindingSnapshot, host_context_digest

    context = verified.context
    return TaskBindingSnapshot(
        task_id="task-a",
        binding_revision=1,
        bound_at=datetime(2026, 9, 6, tzinfo=UTC),
        zebra_policy_digest="a" * 64,
        effective_capabilities=frozenset({"agent.execute"}),
        agent_capability_ceiling={
            "definition_snapshot_digest": "b" * 64,
            "capability_profile_ref": "test@1",
            "capabilities": ["agent.execute"],
            "resolved_at": datetime(2026, 9, 6, tzinfo=UTC),
        },
        host_capability={
            "host_app_id": context.host_app_id,
            "authority_issuer": verified.authority_issuer,
            "namespace_id": context.namespace_id,
            "grant_digest": host_context_digest(context),
            "connector_id": context.host_app_id,
            "connector_profile_revision": 1,
            "connector_profile_digest": "c" * 64,
            "manifest_digest": "d" * 64,
            "capabilities": ["agent.execute"],
            "resource_binding_digest": "e" * 64,
            "bound_at": datetime(2026, 9, 6, tzinfo=UTC),
            "host_context": context,
        },
    )


def test_runtime_task_scope_requires_exact_bound_authority() -> None:
    verified = _verified(scopes=["agent.run"])
    assert extension_runtime_scope_from_task_grant(
        verified, _task_binding(verified)
    ) == extension_runtime_scope_from_grant(verified)


@pytest.mark.parametrize(
    "changes",
    (
        {"sub": "subject-b", "resource_refs": [{"type": "principal", "id": "subject-b"}]},
        {"workspace_ref": "workspace-b"},
        {"namespace_id": "namespace-b"},
        {"iss": "https://issuer-b.example.com"},
    ),
)
def test_runtime_task_scope_rejects_principal_workspace_namespace_and_issuer_drift(
    changes: dict[str, object],
) -> None:
    original = _verified(scopes=["agent.run"])
    with pytest.raises(HostGrantBindingError, match="Task authority drifted"):
        extension_runtime_scope_from_task_grant(
            _verified(scopes=["agent.run"], **changes), _task_binding(original)
        )


@pytest.mark.parametrize(
    "resources",
    (
        [{"type": "event", "id": "event-a"}],
        [
            {"type": "principal", "id": "subject-a"},
            {"type": "principal", "id": "subject-b"},
        ],
    ),
)
def test_runtime_task_scope_requires_exactly_one_principal(
    resources: list[dict[str, str]],
) -> None:
    verified = _verified(scopes=["agent.run"], resource_refs=resources)
    with pytest.raises(HostGrantBindingError, match="exactly one principal"):
        extension_runtime_scope_from_task_grant(verified, _task_binding(verified))
