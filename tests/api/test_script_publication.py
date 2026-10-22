"""Real isolated PostgreSQL and HTTP: exact script approvals, gates and receipts."""

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from agent_core.domain.runtime_bundle_json import json_digest
from agent_core.domain.script_bundle import ScriptBundle
from agent_core.domain.script_definition import ScriptDefinitionVersion
from agent_storage.postgres.host_management import HostManagementStore
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app
from zebra_agent_api.publication_config import load_publication_approval
from zebra_agent_api.script_publication_contract import PATH, script_publication_contract

from tests.agent_core.test_native_script_binding import plan, script
from tests.agent_storage.test_host_management import host_management_dsn  # noqa: F401
from tests.api.test_bundle_management import write
from tests.api.test_publication_management import (
    PATH as BASE_PATH,
)
from tests.api.test_publication_management import (
    evidence,
    materialize,
    publisher,  # noqa: F401
)


def approve(p, **updates):
    p.approval.update(updates)
    p.approval["trust_revision"] += 1
    write(p.path, p.approval)
    value = load_publication_approval(str(p.path), "local")
    HostManagementStore(p.cfg.database_url, deployment_namespace="local").approve(
        value.trust, value.trust_revision - 1
    )
    p.headers["X-Runtime-Trust-Revision"] = str(value.trust_revision)


@pytest.fixture
def scripted(publisher):  # noqa: F811
    p = publisher
    s = script()
    p.plan = plan()
    envelope = {
        "schema_version": "cloud-agent.script-bundle/1",
        "base_bundle": p.bundle,
        "scripts": p.plan.model_dump(mode="json"),
    }
    p.script_bundle = envelope | {"bundle_digest": json_digest(envelope)}
    native = ScriptBundle.model_validate(p.script_bundle)
    catalog = json.loads(Path(p.cfg.runtime_bundle_config).read_text())
    catalog.update(
        schema_version="cloud-agent.execution-catalog/2",
        script_plans=[p.plan.model_dump(mode="json")],
        scripts=[s.manifest.model_dump(mode="json") | {"source": s.source.decode()}],
    )
    write(Path(p.cfg.runtime_bundle_config), catalog)
    approve(
        p,
        references=[*p.approval["references"], "script-bundle/" + native.bundle_digest[7:] + "@1"],
    )
    p.headers["X-Runtime-Publication-Contract"] = script_publication_contract()["contractDigest"]
    return p


def request(p):
    return materialize(p) | {"bundle": p.script_bundle}


def publish(p, version):
    return {
        "action": "publish",
        "operationId": str(uuid4()),
        "expectedRevision": version["revision"],
        "versionId": version["versionId"],
        "evidenceId": evidence(p, version),
    }


def test_materialize_publish_and_original_receipts(scripted):
    p = scripted
    with TestClient(create_http_app(settings=p.cfg, stores=p.stores)) as c:
        body = request(p)
        first = c.post(PATH, headers=p.headers, json=body)
        assert first.status_code == 200, first.text
        result = first.json()["result"]
        assert result["scriptBundleDigest"] == p.script_bundle["bundle_digest"]
        assert result["bundleDigest"] == p.bundle["bundle_digest"]
        frozen = p.registry.get_version(p.scope, UUID(body["versionId"]))
        assert isinstance(frozen, ScriptDefinitionVersion)
        assert frozen.runtime_assembly.script_bundle.model_dump(mode="json") == p.script_bundle
        assert '"source":' not in frozen.model_dump_json()
        assert c.post(PATH, headers=p.headers, json=body).json() == first.json()
        headers = p.headers | {"X-Runtime-Operation": body["operationId"]}
        assert c.get(PATH, headers=headers).json() == first.json()
        assert c.get(BASE_PATH, headers=headers).status_code == 404
        assert c.post(BASE_PATH, headers=p.headers, json=body).status_code == 409
        command = publish(p, result)
        assert c.post(BASE_PATH, headers=p.headers, json=command).status_code == 403
        release = c.post(PATH, headers=p.headers, json=command)
        assert release.status_code == 200, release.text
        assert release.json()["result"]["revision"] == 2
        assert c.post(PATH, headers=p.headers, json=command).json() == release.json()
        assert c.post(BASE_PATH, headers=p.headers, json=command).status_code == 409
        # A newer draft never rewrites the historical immutable Definition3.
        next_body = request(p) | {"version": 2, "expectedRevision": 2}
        assert c.post(PATH, headers=p.headers, json=next_body).status_code == 200
        assert p.registry.get_version(p.scope, UUID(body["versionId"])) == frozen


@pytest.mark.parametrize("missing", ["script", "base"])
def test_exact_reference_missing_rolls_back(scripted, missing):
    p = scripted
    prefix = "script-bundle/" if missing == "script" else "runtime-bundle/"
    approve(p, references=[r for r in p.approval["references"] if not r.startswith(prefix)])
    with TestClient(create_http_app(settings=p.cfg, stores=p.stores)) as c:
        assert c.post(PATH, headers=p.headers, json=request(p)).status_code == 422
        assert p.registry.get_definition(p.scope) is None


def test_versioned_channel_contract_scope_and_strict_transport(scripted):
    p = scripted
    with TestClient(create_http_app(settings=p.cfg, stores=p.stores)) as c:
        body = request(p)
        assert c.post(BASE_PATH, headers=p.headers, json=body).status_code == 422
        assert c.post(PATH, headers=p.headers, json=materialize(p)).status_code == 422
        for value in ("", "sha256:" + "0" * 64):
            headers = p.headers | {"X-Runtime-Publication-Contract": value}
            assert c.post(PATH, headers=headers, json=body).status_code == 409
            assert (
                c.get(PATH, headers=headers | {"X-Runtime-Operation": str(uuid4())}).status_code
                == 409
            )
        for name, value, status in (
            ("Authorization", "Bearer rtsv_" + "a" * 43, 401),
            ("X-Runtime-Product", "foreign", 403),
            ("Cookie", "session=not-authority", 400),
        ):
            assert c.post(PATH, headers=p.headers | {name: value}, json=body).status_code == status
        other = copy.deepcopy(body)
        other["bundle"]["base_bundle"]["manifest"]["scope"]["product_id"] = "foreign"
        other["bundle"]["base_bundle"]["bundle_digest"] = json_digest(
            other["bundle"]["base_bundle"]["manifest"]
        )
        other["bundle"]["bundle_digest"] = json_digest(
            {k: v for k, v in other["bundle"].items() if k != "bundle_digest"}
        )
        assert c.post(PATH, headers=p.headers, json=other).status_code == 403
        base_other = materialize(p) | {"bundle": other["bundle"]["base_bundle"]}
        assert c.post(BASE_PATH, headers=p.headers, json=base_other).status_code == 403
        assert p.registry.get_definition(p.scope) is None


def test_catalog_denial_and_current_publisher_revocation(scripted):
    p = scripted
    catalog = json.loads(Path(p.cfg.runtime_bundle_config).read_text())
    del catalog["script_plans"]
    del catalog["scripts"]
    catalog["schema_version"] = "cloud-agent.execution-catalog/1"
    write(Path(p.cfg.runtime_bundle_config), catalog)
    with TestClient(create_http_app(settings=p.cfg, stores=p.stores)) as c:
        assert c.post(PATH, headers=p.headers, json=request(p)).status_code == 422
        assert p.registry.get_definition(p.scope) is None
        approve(p, actions=["read"])
        assert c.post(PATH, headers=p.headers, json=request(p)).status_code == 403


def test_current_script_grant_and_eval_required_at_publish(scripted):
    p = scripted
    with TestClient(create_http_app(settings=p.cfg, stores=p.stores)) as c:
        first = c.post(PATH, headers=p.headers, json=request(p))
        assert first.status_code == 200, first.text
        result = first.json()["result"]
        command = publish(p, result)
        command["evidenceId"] = evidence(p, result, passed=False)
        assert c.post(PATH, headers=p.headers, json=command).status_code == 403
        command["evidenceId"] = evidence(p, result, actor="untrusted")
        assert c.post(PATH, headers=p.headers, json=command).status_code == 403
        command["evidenceId"] = evidence(p, result)
        approve(
            p,
            references=[r for r in p.approval["references"] if not r.startswith("script-bundle/")],
        )
        assert c.post(PATH, headers=p.headers, json=command).status_code == 403
        assert (
            p.registry.resolve_published(p.scope, environment=p.approval["scope"]["environment"])
            is None
        )


def test_two_replicas_share_definition_cas_and_original_operation(scripted):
    p = scripted

    def call(body):
        with TestClient(create_http_app(settings=p.cfg, stores=p.stores)) as c:
            return c.post(PATH, headers=p.headers, json=body)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(call, [request(p), request(p)]))
    assert sorted(r.status_code for r in results) == [200, 409]
    winner = next(r.json()["result"] for r in results if r.status_code == 200)
    body = publish(p, winner)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(call, [body, body]))
    assert [r.status_code for r in results] == [200, 200]
    assert results[0].json() == results[1].json()


def test_catalog_removed_after_materialization_blocks_release(scripted):
    p = scripted
    with TestClient(create_http_app(settings=p.cfg, stores=p.stores)) as c:
        response = c.post(PATH, headers=p.headers, json=request(p))
        assert response.status_code == 200, response.text
        command = publish(p, response.json()["result"])
        catalog = json.loads(Path(p.cfg.runtime_bundle_config).read_text())
        catalog["scripts"][0]["source"] += "# tampered"
        write(Path(p.cfg.runtime_bundle_config), catalog)
        assert c.post(PATH, headers=p.headers, json=command).status_code == 422
        assert (
            p.registry.resolve_published(p.scope, environment=p.approval["scope"]["environment"])
            is None
        )


def test_plain_bundle_receipts_cannot_be_read_or_published_through_script_channel(scripted):
    p = scripted
    with TestClient(create_http_app(settings=p.cfg, stores=p.stores)) as c:
        body = materialize(p)
        response = c.post(BASE_PATH, headers=p.headers, json=body)
        assert response.status_code == 200, response.text
        assert (
            c.get(
                PATH, headers=p.headers | {"X-Runtime-Operation": body["operationId"]}
            ).status_code
            == 404
        )
        command = publish(p, response.json()["result"])
        assert c.post(PATH, headers=p.headers, json=command).status_code == 403
        old = c.post(BASE_PATH, headers=p.headers, json=command)
        assert old.status_code == 200, old.text
        assert c.post(PATH, headers=p.headers, json=command).status_code == 409


def test_late_current_approval_change_rolls_back_version_and_receipt(scripted, monkeypatch):
    from zebra_agent_api import publication_management

    p = scripted
    original = publication_management.mutate_publication

    def late_change(*args, **kwargs):
        result = original(*args, **kwargs)
        # The operator file changes during the mutation; no shared grant is forged.
        write(p.path, p.approval | {"actions": ["read"]})
        return result

    monkeypatch.setattr(publication_management, "mutate_publication", late_change)
    with TestClient(create_http_app(settings=p.cfg, stores=p.stores)) as c:
        body = request(p)
        assert c.post(PATH, headers=p.headers, json=body).status_code == 403
        assert p.registry.get_definition(p.scope) is None
        write(p.path, p.approval)
        assert (
            c.get(
                PATH, headers=p.headers | {"X-Runtime-Operation": body["operationId"]}
            ).status_code
            == 404
        )


def process_publish(settings, headers, body):
    """Separate interpreter/DB connections; production perform owns transaction/CAS."""
    from agent_storage.postgres.host_management import HostManagementConflict
    from zebra_agent_api.publication_management import perform

    try:
        response = perform(
            settings,
            "local",
            headers["Authorization"].removeprefix("Bearer "),
            {key: [value] for key, value in headers.items()}
            | {key.lower(): [value] for key, value in headers.items()},
            "POST",
            json.dumps(body).encode(),
            scripts=True,
        )
        return response.status_code, json.loads(response.body)
    except HostManagementConflict:
        return 409, {}


def test_independent_processes_share_cas_and_replay(scripted):
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor

    p = scripted
    with ProcessPoolExecutor(2, mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = [pool.submit(process_publish, p.cfg, p.headers, request(p)) for _ in range(2)]
        results = [f.result(timeout=30) for f in futures]
        assert sorted(status for status, _ in results) == [200, 409]
        version = next(result["result"] for status, result in results if status == 200)
        body = publish(p, version)
        results = [pool.submit(process_publish, p.cfg, p.headers, body) for _ in range(2)]
        completed = [f.result(timeout=30) for f in results]
        assert all(status == 200 for status, _ in completed)
        assert completed[0] == completed[1]


def test_mounted_api_keeps_explicit_script_channel(scripted):
    from fastapi import FastAPI

    p = scripted
    parent = FastAPI()
    parent.mount("/native", create_http_app(settings=p.cfg, stores=p.stores))
    with TestClient(parent) as c:
        response = c.post("/native" + PATH, headers=p.headers, json=request(p))
        assert response.status_code == 200, response.text
        assert response.json()["contractVersion"] == "script-publication/1"
        assert (
            c.post(
                "/native" + BASE_PATH, headers=p.headers, json=request(p) | {"expectedRevision": 1}
            ).status_code
            == 422
        )


def test_non_string_ids_are_rejected_in_both_publisher_channels(scripted):
    p = scripted
    with TestClient(create_http_app(settings=p.cfg, stores=p.stores)) as c:
        for path, factory in ((PATH, request), (BASE_PATH, materialize)):
            for field in ("operationId", "versionId"):
                for invalid in (None, True, 17, {}, []):
                    body = factory(p) | {field: invalid}
                    assert c.post(path, headers=p.headers, json=body).status_code == 422
        assert p.registry.get_definition(p.scope) is None
