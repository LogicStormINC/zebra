"""Real disposable PG, current scoped approval, atomic native Profile operations."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import psycopg
import pytest
from agent_storage.postgres.client_capabilities import PostgresClientCapabilityRegistry
from agent_storage.postgres.host_management import HostManagementStore
from fastapi import FastAPI
from fastapi.testclient import TestClient
from zebra_agent_api.frontend_profile_management import PATH, register_frontend_profile_management
from zebra_agent_api.host_registry_config import load_host_management_config

from tests.api.test_client_runtime_api import _profile
from tests.api.test_host_connector_management import HEADERS, config, dsn, write

owned_dsn = dsn


@pytest.fixture
def prepared(tmp_path, owned_dsn):
    from zebra_agent_config import load_settings

    namespace = "frontend-" + uuid4().hex
    value = config(namespace)
    value.pop("connectorProfile")
    value["actions"] = ["frontend-profile.read", "frontend-profile.write"]
    value["frontendProfile"] = (
        _profile().model_copy(update={"published_at": None}).model_dump(mode="json")
    )
    path = tmp_path / "frontend.json"
    write(path, value)
    approval = load_host_management_config(str(path), namespace)
    store = HostManagementStore(owned_dsn, deployment_namespace=namespace)
    store.approve(approval.trust, 0)
    # Register approved Host using its independently governed existing interface.
    store.apply(approval.trust, approval.registry, 0, str(uuid4()))
    settings = replace(load_settings({}), database_url=owned_dsn, host_management_config=str(path))
    app = FastAPI()
    register_frontend_profile_management(app, settings, namespace)
    return path, value, owned_dsn, namespace, app


def change(expected=0, active=True):
    return {"expectedRevision": expected, "operationId": str(uuid4()), "active": active}


def test_native_profile_lifecycle_cas_current_replay_and_no_reactivation(prepared):
    _, _, url, ns, app = prepared
    with TestClient(app) as one, TestClient(app) as two:
        initial = one.get(PATH, headers=HEADERS)
        assert initial.status_code == 200 and initial.json()["revision"] == 0
        body = change()
        published = one.put(PATH, headers=HEADERS, json=body)
        assert published.status_code == 200, published.text
        out = published.json()
        assert out["contractVersion"] == "frontend-profile-management/1"
        assert out["revision"] == 1 and out["active"] and out["available"]
        profile = out["profile"]
        native = PostgresClientCapabilityRegistry(url, deployment_namespace=ns)
        assert (
            native.get_profile(profile["frontendAppId"], 1).profile_digest
            == profile["profileDigest"]
        )
        assert two.put(PATH, headers=HEADERS, json=body).json()["replayed"]
        assert two.put(PATH, headers=HEADERS, json=change()).status_code == 409
        assert two.put(PATH, headers=HEADERS, json={**body, "active": False}).status_code == 409
        revoked = two.put(PATH, headers=HEADERS, json=change(1, False))
        assert revoked.status_code == 200 and not revoked.json()["active"]
        assert one.get(PATH, headers=HEADERS).json()["profile"]["lifecycle"] == "revoked"
        # Historical operation response stays historical, current read stays revoked.
        assert one.put(PATH, headers=HEADERS, json=body).json()["active"]
        assert not one.get(PATH, headers=HEADERS).json()["available"]
        assert one.put(PATH, headers=HEADERS, json=change(2)).status_code == 409
    with psycopg.connect(url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM frontend_profile_management_receipts "
                "WHERE deployment_namespace=%s",
                (ns,),
            ).fetchone()[0]
            == 2
        )


@pytest.mark.parametrize("fault", ["product", "token", "action", "approval", "expiry", "body"])
def test_scope_and_current_approval_before_read_or_replay(prepared, fault):
    path, value, url, ns, app = prepared
    with TestClient(app) as client:
        body = change()
        assert client.put(PATH, headers=HEADERS, json=body).status_code == 200
        headers = dict(HEADERS)
        expected = 403
        if fault == "product":
            headers["X-Runtime-Product"] = "foreign"
        elif fault == "token":
            headers["Authorization"] = "Bearer rthm_" + "b" * 43
            expected = 401
        elif fault == "body":
            body["frontendAppId"] = "foreign"
            expected = 400
        else:
            value["trustRevision"] = 2
            if fault == "action":
                value["actions"] = ["frontend-profile.read"]
            if fault == "expiry":
                value["expiresAt"] = "2000-01-01T00:00:00Z"
            write(path, value)
            headers["X-Runtime-Trust-Revision"] = "2"
            if fault == "approval":
                approved = load_host_management_config(str(path), ns)
                HostManagementStore(url, deployment_namespace=ns).approve(approved.trust, 1)
                # A stale replica cannot use old config against a new shared approval.
                headers["X-Runtime-Trust-Revision"] = "1"
                value["trustRevision"] = 1
                write(path, value)
                expected = 503
            elif fault != "expiry" and fault != "action":
                expected = 503
        response = client.put(PATH, headers=headers, json=body)
        assert response.status_code == expected, response.text


def test_two_instances_cas_only_one_wins_and_audit_failure_rolls_back(prepared):
    _, _, url, ns, app = prepared
    with TestClient(app) as one, TestClient(app) as two:

        def apply(client):
            return client.put(PATH, headers=HEADERS, json=change()).status_code

        with ThreadPoolExecutor(2) as executor:
            futures = [executor.submit(apply, c) for c in (one, two)]
            assert sorted(f.result() for f in futures) == [200, 409]
        # Namespace-specific constraint injection must roll back lifecycle and revision.
        with psycopg.connect(url) as conn:
            from psycopg import sql

            name = "deny_" + uuid4().hex
            conn.execute(
                sql.SQL(
                    "ALTER TABLE frontend_profile_management_receipts ADD CONSTRAINT {} "
                    "CHECK (deployment_namespace <> {}) NOT VALID"
                ).format(sql.Identifier(name), sql.Literal(ns))
            )
        try:
            assert one.put(PATH, headers=HEADERS, json=change(1, False)).status_code == 503
            current = one.get(PATH, headers=HEADERS).json()
            assert current["active"] and current["revision"] == 1
        finally:
            with psycopg.connect(url) as conn:
                conn.execute(
                    sql.SQL(
                        "ALTER TABLE frontend_profile_management_receipts DROP CONSTRAINT {}"
                    ).format(sql.Identifier(name))
                )


def test_approved_scope_cannot_claim_another_products_frontend_app(prepared):
    path, value, url, ns, app = prepared
    with TestClient(app) as client:
        assert client.put(PATH, headers=HEADERS, json=change()).status_code == 200
    # Even explicit second Host approval cannot overwrite the first product's owned App.
    value["productId"] = "b"
    value["registry"]["hostAppId"] = "host-b"
    value["registry"]["namespaceId"] = "tenant-b"
    write(path, value)
    approved = load_host_management_config(str(path), ns)
    HostManagementStore(url, deployment_namespace=ns).approve(approved.trust, 0)
    with TestClient(app) as client:
        headers = {**HEADERS, "X-Runtime-Product": "b"}
        assert client.get(PATH, headers=headers).status_code == 503
        assert client.put(PATH, headers=headers, json=change()).status_code == 503


def test_explicit_postgres_stores_compose_frontend_integration(prepared):
    from agent_storage import postgres_control_plane_stores
    from zebra_agent_api import create_app

    _, _, url, ns, _ = prepared
    from agent_core.domain.cloud_scope import OpaqueAuthorityScope

    scope = OpaqueAuthorityScope(authority_issuer="https://owned.example", namespace_id="tenant-a")
    stores = postgres_control_plane_stores(
        url,
        deployment_namespace=ns,
        memory_cursor_signing_key=b"a" * 32,
        artifact_objects=object(),
        history_scope=scope,
        continuation_scope=scope,
    )
    from zebra_agent_config import load_settings

    settings = replace(
        load_settings({}),
        profile="cloud",
        database_url=url,
        client_integration_enabled=True,
        development_unrestricted=True,
    )
    app = create_app(settings=settings, stores=stores)
    assert app.client_platform is not None
    app.client_platform.require_client_stores()


def test_legacy_shared_app_cannot_be_claimed_or_globally_revoked_by_one_host(prepared):
    from agent_control_plane.frontend_profiles import FrontendProfileService

    _, _, url, ns, app = prepared
    registry = PostgresClientCapabilityRegistry(url, deployment_namespace=ns)
    service = FrontendProfileService(registry)
    profile = _profile()
    service.publish(profile)
    service.bind(
        host_app_id="legacy-host",
        namespace_id="legacy-tenant",
        frontend_app_id=profile.frontend_app_id,
        revision=1,
        profile_digest=profile.profile_digest,
    )
    with TestClient(app) as client:
        assert client.put(PATH, headers=HEADERS, json=change()).status_code == 409
        assert client.put(PATH, headers=HEADERS, json=change(active=False)).status_code == 409
        assert client.get(PATH, headers=HEADERS).json()["revision"] == 0
    assert registry.get_profile(profile.frontend_app_id, 1).lifecycle.value == "published"
    assert registry.get_binding_for_host("legacy-host", "legacy-tenant", profile.frontend_app_id)


def test_legacy_foreign_binding_and_scoped_revocation_never_both_commit(prepared):
    from agent_control_plane.frontend_profiles import FrontendProfileService
    from agent_core.domain.client_capabilities import ClientCapabilityError

    _, _, url, ns, app = prepared
    registry = PostgresClientCapabilityRegistry(url, deployment_namespace=ns)
    service = FrontendProfileService(registry)
    profile = _profile()
    with TestClient(app) as client:
        original = change()
        assert client.put(PATH, headers=HEADERS, json=original).status_code == 200

        def bind_foreign():
            try:
                service.bind(
                    host_app_id="legacy-host",
                    namespace_id="legacy-tenant",
                    frontend_app_id=profile.frontend_app_id,
                    revision=1,
                    profile_digest=profile.profile_digest,
                )
                return True
            except ClientCapabilityError:
                return False

        with ThreadPoolExecutor(2) as pool:
            legacy = pool.submit(bind_foreign)
            scoped = pool.submit(client.put, PATH, headers=HEADERS, json=change(1, False))
            bound, response = legacy.result(), scoped.result()
        assert (bound, response.status_code) in {(True, 409), (False, 200)}
        assert registry.get_profile(profile.frontend_app_id, 1).lifecycle.value == (
            "published" if bound else "revoked"
        )
        # Historical replay is read-only and cannot revive either current state.
        assert client.put(PATH, headers=HEADERS, json=original).json()["replayed"]
