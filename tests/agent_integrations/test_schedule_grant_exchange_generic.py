"""Real signed renewal with opaque product resources and bounded narrowing."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from agent_core.application.task_schedule_materializer import ScheduleAuthorityRejected
from agent_core.domain.host_authority import HostResourceRef
from agent_integrations import HttpScheduleAuthorityRevalidator, ScheduleGrantExchangeSettings
from agent_security import HostGrantVerificationConfig, JwtAlgorithm, PyJwtHostGrantDecoder
from cryptography.hazmat.primitives.asymmetric import rsa

from tests.agent_integrations.test_schedule_grant_exchange import StaticJwks, authority_fixture


def renewal_fixture(transform=None):
    binding, firing = authority_fixture()
    owner = binding.owner.model_copy(update={"host_app_id": "catalog"})
    context = binding.host_context.model_copy(
        update={
            "host_app_id": "catalog",
            "origin": "https://catalog.example",
            "resource_refs": (
                HostResourceRef(type="principal", id=owner.principal_id),
                HostResourceRef(type="catalog.record", id="record-1"),
            ),
        }
    )
    binding = binding.model_copy(update={"owner": owner, "host_context": context})
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    verification = HostGrantVerificationConfig(
        issuer="https://broker.example",
        audience="zebra",
        jwks_uri="https://broker.example/jwks",
        allowed_origins=(context.origin,),
        algorithms=frozenset({JwtAlgorithm.RS256}),
    )
    seen = []

    def exchange(request):
        body = json.loads(request.content)
        seen.append(body)
        claims = {
            "iss": verification.issuer,
            "aud": "zebra",
            "sub": owner.principal_id,
            "jti": "fresh",
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "host_app_id": owner.host_app_id,
            "namespace_id": owner.tenant_id,
            "workspace_ref": owner.workspace_id,
            "origin": context.origin,
            "policy_version": context.policy_version,
            "scopes": ["agent.run", "source.read", "extra.read"],
            "resource_refs": [
                {"type": "thread", "id": str(firing.schedule_id)},
                {"type": "run", "id": str(firing.fire_id)},
                {"type": "principal", "id": owner.principal_id},
                {"type": "catalog.record", "id": "record-1"},
                {"type": "catalog.record", "id": "unrequested"},
            ],
            "limits": context.limits.model_dump(),
        }
        if transform:
            transform(claims)
        token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})
        return httpx.Response(200, json={"grant": token})

    adapter = HttpScheduleAuthorityRevalidator(
        ScheduleGrantExchangeSettings(
            exchange_url="https://broker.example/exchange",
            workload_identity="scheduler",
            workload_shared_secret="secret",
            verification=verification,
        ),
        PyJwtHostGrantDecoder(StaticJwks(key, "test")),
        client=httpx.Client(transport=httpx.MockTransport(exchange)),
        now=lambda: now,
    )
    return adapter, binding, firing, seen


def test_generic_signed_renewal_preserves_opaque_refs_and_drops_extras():
    adapter, binding, firing, seen = renewal_fixture()
    result = adapter.revalidate(binding, firing)
    assert seen[0]["principal"] == {"userId": "user-1", "workspaceId": "workspace-1"}
    assert seen[0]["resourceRefs"] == [{"type": "catalog.record", "id": "record-1"}]
    assert set(result.host_context.scopes) == {"agent.run", "source.read"}
    assert {r.key for r in result.host_context.resource_refs} == {
        ("thread", str(firing.schedule_id)),
        ("run", str(firing.fire_id)),
        ("principal", "user-1"),
        ("catalog.record", "record-1"),
    }


@pytest.mark.parametrize("kind", ["thread", "run", "principal"])
@pytest.mark.parametrize("duplicate", [False, True])
def test_generic_renewal_rejects_wrong_or_multiple_execution_bindings(kind, duplicate):
    def tamper(claims):
        if duplicate:
            claims["resource_refs"].append({"type": kind, "id": "other"})
        else:
            next(r for r in claims["resource_refs"] if r["type"] == kind)["id"] = "other"

    adapter, binding, firing, _ = renewal_fixture(tamper)
    with pytest.raises(ScheduleAuthorityRejected):
        adapter.revalidate(binding, firing)


@pytest.mark.parametrize(
    "field,value",
    [
        ("sub", "other"),
        ("namespace_id", "other"),
        ("workspace_ref", "other"),
        ("host_app_id", "other"),
        ("origin", "https://other.example"),
        ("policy_version", "other"),
        ("iss", "https://other.example"),
        ("scopes", ["agent.run"]),
    ],
)
def test_generic_renewal_rejects_identity_or_scope_drift(field, value):
    adapter, binding, firing, _ = renewal_fixture(lambda c: c.update({field: value}))
    with pytest.raises(ScheduleAuthorityRejected):
        adapter.revalidate(binding, firing)


def test_generic_renewal_rejects_revoked_resource():
    def revoke(claims):
        claims["resource_refs"] = [
            r for r in claims["resource_refs"] if r["type"] != "catalog.record"
        ]

    adapter, binding, firing, _ = renewal_fixture(revoke)
    with pytest.raises(ScheduleAuthorityRejected):
        adapter.revalidate(binding, firing)


def test_generic_renewal_never_increases_technical_limits():
    def enlarge(claims):
        claims["limits"] = {k: v * 2 for k, v in claims["limits"].items()}

    adapter, binding, firing, _ = renewal_fixture(enlarge)
    assert adapter.revalidate(binding, firing).host_context.limits == binding.host_context.limits


def test_unknown_schedule_protocol_fails_before_network():
    adapter, _, _, _ = renewal_fixture()
    with pytest.raises(ValueError, match="protocol"):
        replace(adapter.settings, protocol="unknown")
