"""Actual native HTTP/PG publisher authority, atomicity, retry and gate checks."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from agent_core.domain.agent_definitions import AgentDefinitionScope
from agent_storage.postgres.agent_registry import AgentDefinitionEvalEvidence, PostgresAgentRegistry
from agent_storage.postgres.host_management import HostManagementStore
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app
from zebra_agent_api.publication_config import load_publication_approval

from tests.agent_storage.test_host_management import host_management_dsn  # noqa: F401
from tests.api.test_bundle_management import configured_fixture, write

TOKEN = "rtpub_" + "c" * 43
PATH = "/management/v1/runtime-publication"


@pytest.fixture
def publisher(tmp_path, host_management_dsn):  # noqa: F811
    from types import SimpleNamespace

    from agent_storage import postgres_control_plane_stores

    configured, _, _, bundle, headers = configured_fixture(tmp_path)
    definition = str(uuid4())
    refs = {
        "model_policy_ref": "model/default@1",
        "tool_profile_ref": "tools/default@1",
        "memory_policy_ref": "memory/default@1",
        "security_policy_ref": "security/default@1",
        "evaluation_profile_ref": "eval/default@1",
        "runtime_profile_ref": "runtime/default@1",
    }
    template = {
        "name": "public",
        "description": "owned test",
        "skill_snapshot_digest": "a" * 64,
        **refs,
    }
    approval = {
        "schema_version": "cloud-agent.publication-approval/1",
        "scope": bundle["manifest"]["scope"],
        "audience": "management-a",
        "actor": "publisher-" + uuid4().hex[:12],
        "definition_id": definition,
        "trust_revision": 1,
        "credential_sha256": hashlib.sha256(TOKEN.encode()).hexdigest(),
        "expires_at": "2099-01-01T00:00:00Z",
        "actions": ["materialize", "publish", "read"],
        "references": [
            *refs.values(),
            "a" * 64,
            "runtime-bundle/" + bundle["bundle_digest"][7:] + "@1",
        ],
        "template": template,
        "evaluator_actors": ["native-evaluator"],
        "policy_version": "eval-policy/1",
        "consumer_hosts": ["consumer-" + uuid4().hex[:12]],
    }
    path = tmp_path / "publisher.json"
    write(path, approval)
    cfg = replace(
        configured, database_url=host_management_dsn, publication_management_config=str(path)
    )
    trust = load_publication_approval(str(path), "local").trust
    HostManagementStore(host_management_dsn, deployment_namespace="local").approve(trust, 0)
    # Cloud storage real; HTTP business auth remains a separate trust boundary.
    from agent_core.domain.cloud_scope import OpaqueAuthorityScope

    class NoObjects:
        def read(self, *args, **kwargs):
            raise AssertionError("no artifact access")

    scope = OpaqueAuthorityScope(
        authority_issuer=approval["scope"]["authority_issuer"], namespace_id="local"
    )
    stores = postgres_control_plane_stores(
        host_management_dsn,
        deployment_namespace="local",
        memory_cursor_signing_key=b"a" * 32,
        artifact_objects=NoObjects(),
        history_scope=scope,
        continuation_scope=scope,
    )
    return SimpleNamespace(
        cfg=cfg,
        path=path,
        approval=approval,
        bundle=bundle,
        headers={**headers, "Authorization": "Bearer " + TOKEN},
        stores=stores,
        registry=PostgresAgentRegistry(host_management_dsn, deployment_namespace="local"),
        scope=AgentDefinitionScope(
            authority_issuer=approval["scope"]["authority_issuer"],
            namespace_id="local",
            definition_id=UUID(definition),
        ),
    )


def materialize(p):
    return {
        "action": "materialize",
        "operationId": str(uuid4()),
        "expectedRevision": 0,
        "versionId": str(uuid4()),
        "version": 1,
        "bundle": p.bundle,
    }


def evidence(p, version, *, passed=True, actor="native-evaluator"):
    ev = AgentDefinitionEvalEvidence(
        authority_issuer=p.scope.authority_issuer,
        namespace_id="local",
        definition_id=p.scope.definition_id,
        version_id=UUID(version["versionId"]),
        evidence_id=uuid4(),
        definition_digest=version["definitionDigest"],
        passed=passed,
        evaluator_actor=actor,
        case_summary={"policy_version": "eval-policy/1"},
    )
    p.registry.record_eval_evidence(ev)
    return str(ev.evidence_id)


def test_public_http_materialize_gate_publish_replay(publisher):
    p = publisher
    payload = materialize(p)
    with TestClient(create_http_app(settings=p.cfg, stores=p.stores)) as c:
        first = c.post(PATH, headers=p.headers, json=payload)
        assert first.status_code == 200, first.text
        version = first.json()["result"]
        assert c.post(PATH, headers=p.headers, json=payload).json() == first.json()
        result = c.get(PATH, headers={**p.headers, "X-Runtime-Operation": payload["operationId"]})
        assert result.json() == first.json()
        publish = {
            "action": "publish",
            "operationId": str(uuid4()),
            "expectedRevision": 1,
            "versionId": payload["versionId"],
            "evidenceId": str(uuid4()),
        }
        assert c.post(PATH, headers=p.headers, json=publish).status_code == 403
        publish["evidenceId"] = evidence(p, version, passed=False)
        assert c.post(PATH, headers=p.headers, json=publish).status_code == 403
        publish["evidenceId"] = evidence(p, version)
        published = c.post(PATH, headers=p.headers, json=publish)
        assert published.status_code == 200, published.text
        assert published.json()["result"]["revision"] == 2
        assert c.post(PATH, headers=p.headers, json=publish).json() == published.json()
        assert p.registry.resolve_published(
            p.scope, environment=p.approval["scope"]["environment"]
        ).version_id == UUID(payload["versionId"])
        changed = {**payload, "version": 2}
        assert c.post(PATH, headers=p.headers, json=changed).status_code == 409
        assert (
            c.post(PATH, headers=p.headers, json={**materialize(p), "version": 2}).status_code
            == 409
        )


def test_scope_credentials_exact_reference_and_rotation(publisher):
    p = publisher
    with TestClient(create_http_app(settings=p.cfg, stores=p.stores)) as c:
        for token in ["rtbv_" + "a" * 43, "rthm_" + "a" * 43, TOKEN[:-1] + "d"]:
            assert (
                c.post(
                    PATH,
                    headers={**p.headers, "Authorization": "Bearer " + token},
                    json=materialize(p),
                ).status_code
                == 401
            )
        assert (
            c.post(
                PATH, headers={**p.headers, "X-Runtime-Product": "other"}, json=materialize(p)
            ).status_code
            == 403
        )
        payload = materialize(p)
        write(
            p.path, {**p.approval, "references": p.approval["references"][:-1], "trust_revision": 2}
        )
        approval = load_publication_approval(str(p.path), "local")
        HostManagementStore(p.cfg.database_url, deployment_namespace="local").approve(
            approval.trust, 1
        )
        assert c.post(PATH, headers=p.headers, json=payload).status_code == 403
        response = c.post(
            PATH, headers={**p.headers, "X-Runtime-Trust-Revision": "2"}, json=payload
        )
        assert response.status_code == 422, response.text
        assert (
            p.registry.get_definition(p.scope) is None
        )  # Failed materialization rolled draft/metadata back.


def test_two_replicas_cas_single_winner(publisher):
    p = publisher

    def call(payload):
        with TestClient(create_http_app(settings=p.cfg, stores=p.stores)) as c:
            return c.post(PATH, headers=p.headers, json=payload).status_code

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(call, [materialize(p), materialize(p)]))
    assert sorted(results) == [200, 409]


def test_real_http_business_host_consumes_without_publisher_grant(publisher, tmp_path):
    import time

    import jwt
    from agent_core.domain.host_authority import (
        HostContextEnvelope,
        HostResourceRef,
        HostTechnicalLimits,
    )
    from agent_security import PyJwtHostGrantDecoder
    from agent_storage import (
        HostRegistryRecord,
        PostgresHostAuthorityStore,
        bootstrap_control_plane_epoch,
    )
    from cryptography.hazmat.primitives.asymmetric import rsa
    from zebra_agent_api.host_auth import PostgresHostGrantRequestAuthorizer

    p = publisher
    bootstrap_control_plane_epoch(p.cfg.database_url, deployment_namespace="local")
    host = p.approval["consumer_hosts"][0]
    issuer = p.scope.authority_issuer
    authority = PostgresHostAuthorityStore(p.cfg.database_url, deployment_namespace="local")
    record = HostRegistryRecord(
        host, "local", issuer, "native", issuer + "/jwks", (issuer,), ("RS256",), "user/1"
    )
    authority.upsert_registry(record)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Key:
        def resolve(self, uri, token, **kwargs):
            assert uri == issuer + "/jwks"
            return key.public_key()

    authorizer = PostgresHostGrantRequestAuthorizer(
        registry=authority, decoder=PyJwtHostGrantDecoder(Key())
    )
    context = HostContextEnvelope(
        grant_id="ignored",
        host_app_id=host,
        namespace_id="local",
        workspace_ref="workspace://owned",
        resource_refs=(
            HostResourceRef(type="principal", id="principal"),
            HostResourceRef(type="thread", id=str(uuid4())),
        ),
        scopes=("agent.run",),
        limits=HostTechnicalLimits(
            max_runtime_seconds=300, max_model_tokens=10000, max_artifact_bytes=1048576
        ),
        origin=issuer,
        policy_version="user/1",
    )

    def headers():
        claims = context.model_dump(mode="json", exclude={"grant_id", "expires_at"})
        now = int(time.time())
        claims.update(
            iss=issuer,
            aud="native",
            sub="principal",
            jti=str(uuid4()),
            iat=now - 1,
            nbf=now - 1,
            exp=now + 300,
        )
        return {
            "Authorization": "Bearer " + jwt.encode(claims, key, algorithm="RS256"),
            "Origin": issuer,
            "Idempotency-Key": str(uuid4()),
        }

    with TestClient(
        create_http_app(
            settings=replace(p.cfg, profile="cloud"),
            stores=p.stores,
            host_grant_authorizer=authorizer,
        )
    ) as c:
        request = materialize(p)
        version = c.post(PATH, headers=p.headers, json=request).json()["result"]
        body = {
            "prompt": "hello",
            "workspace": str(tmp_path / "workspace"),
            "execute": False,
            "definition_id": str(p.scope.definition_id),
            "definition_environment": p.approval["scope"]["environment"],
        }
        assert c.post("/tasks", headers=headers(), json=body).status_code == 409
        publish = {
            "action": "publish",
            "operationId": str(uuid4()),
            "expectedRevision": 1,
            "versionId": request["versionId"],
            "evidenceId": evidence(p, version),
        }
        assert c.post(PATH, headers=p.headers, json=publish).status_code == 200
        assert c.post("/tasks", headers=p.headers, json=body).status_code == 403
        admitted = c.post("/tasks", headers=headers(), json=body)
        assert admitted.status_code == 201, admitted.text
        assert (
            c.post(
                "/agent-definitions/" + str(p.scope.definition_id) + "/draft",
                headers=headers(),
                json=p.approval["template"],
            ).status_code
            == 403
        )
        assert (
            c.post(
                "/tasks", headers=headers(), json={**body, "definition_environment": "other"}
            ).status_code
            == 403
        )
        # A legacy privileged publisher may share issuer/namespace/Definition while
        # publishing a Version for another product. Consumption must still fail closed.
        import copy
        from datetime import UTC, datetime

        from agent_core.domain.agent_definitions import AgentRelease
        from agent_core.domain.bundle_definition import BundleDefinitionVersion
        from agent_core.domain.identifiers import AgentDefinitionVersionId, AgentReleaseId
        from agent_core.domain.runtime_bundle import parse_runtime_bundle
        from agent_core.domain.runtime_bundle_json import canonical_json_bytes, json_digest
        from zebra_agent_config.bundle_settings import load_execution_catalog

        other = copy.deepcopy(p.bundle)
        other["manifest"]["scope"]["product_id"] = "foreign-product"
        other["bundle_digest"] = json_digest(other["manifest"])
        bundle = parse_runtime_bundle(canonical_json_bytes(other))
        catalog = load_execution_catalog(p.cfg.runtime_bundle_config).model_copy(
            update={"scope": bundle.manifest.scope}
        )
        current = p.registry.get_version(
            p.scope, AgentDefinitionVersionId(UUID(request["versionId"]))
        )
        foreign = BundleDefinitionVersion(
            **current.model_dump(
                exclude={"version_id", "version", "definition_digest", "runtime_assembly"}
            ),
            version_id=AgentDefinitionVersionId(uuid4()),
            version=2,
            runtime_assembly=catalog.resolve(bundle),
        )
        p.registry.save_version(foreign)
        p.registry.append_release(
            AgentRelease.from_version(
                foreign,
                release_id=AgentReleaseId(uuid4()),
                environment=p.approval["scope"]["environment"],
                actor_ref="legacy-operator",
                effective_at=datetime.now(UTC),
            )
        )
        denied = c.post("/tasks", headers=headers(), json=body)
        assert denied.status_code == 403, denied.text
        authority.upsert_registry(replace(record, active=False))
        assert c.post("/tasks", headers=headers(), json=body).status_code == 403


def test_publisher_private_arrays_remain_strict_and_version_bounds(publisher):
    p = publisher
    for field, value in [
        ("actions", {"read": True}),
        ("consumer_hosts", {"host": True}),
        ("references", {"reference": True}),
        ("evaluator_actors", {"evaluator": True}),
    ]:
        write(p.path, {**p.approval, field: value})
        with pytest.raises((ValueError, TypeError)):
            load_publication_approval(str(p.path), "local")
    write(p.path, p.approval)
    with TestClient(create_http_app(settings=p.cfg, stores=p.stores)) as c:
        payload = materialize(p)
        assert (
            c.post(PATH, headers=p.headers, json={**payload, "version": 2**53}).status_code == 422
        )
        assert p.registry.get_definition(p.scope) is None
