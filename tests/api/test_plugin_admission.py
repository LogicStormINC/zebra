"""Public product contract and real shared approval/receipt checks; no execution."""

import base64
import copy
import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agent_integrations.plugins.package_integrity import load_plugin_package
from agent_storage.postgres.host_management import HostManagementStore
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict
from zebra_agent_api import create_http_app
from zebra_agent_api.plugin_admission import register_plugin_admission
from zebra_agent_api.plugin_admission_config import load_plugin_approval
from zebra_agent_api.plugin_admission_contract import (
    CONTRACT_PATH,
    HEADER,
    PATH,
    plugin_admission_contract,
)
from zebra_agent_config.plugin_settings import PluginSettings

from tests.agent_integrations.test_plugin_publications import Objects, bundle
from tests.agent_storage.test_host_management import host_management_dsn  # noqa: F401
from tests.api.test_bundle_management import configured_fixture, write

TOKEN = "rtpa_" + "p" * 43


@pytest.fixture
def admitted(tmp_path, host_management_dsn):  # noqa: F811
    active, _, old, _, headers = configured_fixture(tmp_path)
    root = tmp_path / "packages"
    root.mkdir()
    bundle(root / "input")
    (root / "input" / "README.md").write_text("Trusted MCP descriptor, not code execution")
    package = load_plugin_package(root / "input")
    (root / "input").rename(root / package.package_digest[7:])
    approval = {
        **old,
        "schema_version": "cloud-agent.plugin-admission-approval/1",
        "scope": {**old["scope"], "target_id": "target-" + uuid4().hex},
        "package_digests": [package.package_digest],
        "credential_sha256": hashlib.sha256(TOKEN.encode()).hexdigest(),
        "actions": ["plugin.contract.read", "plugin.validate", "plugin.publish", "plugin.read"],
    }
    path = tmp_path / "plugin-approval.json"
    write(path, approval)
    cfg = replace(
        active,
        database_url="postgresql://postgres:disposable@127.0.0.1:"
        + conninfo_to_dict(host_management_dsn)["port"]
        + "/postgres",
        plugin_admission_config=str(path),
        plugins=PluginSettings(bundle_root=str(root)),
    )
    store = HostManagementStore(host_management_dsn, deployment_namespace="local")
    store.approve(load_plugin_approval(str(path), "local").trust, 0)
    objects = Objects()
    app = FastAPI()
    register_plugin_admission(app, cfg, "local", SimpleNamespace(artifact_objects=objects))
    return SimpleNamespace(
        app=app,
        cfg=cfg,
        approval=approval,
        path=path,
        store=store,
        objects=objects,
        package=package,
        headers={
            **headers,
            "Authorization": "Bearer " + TOKEN,
            HEADER: plugin_admission_contract()["contractDigest"],
        },
    )


def validate_request(p):
    directory = p.cfg.plugins.bundle_root + "/" + p.package.package_digest[7:]
    from pathlib import Path

    return {
        "action": "validate",
        "scope": p.approval["scope"],
        "files": [
            {"path": f.name, "content_base64": base64.b64encode(f.read_bytes()).decode()}
            for f in sorted(Path(directory).iterdir())
        ],
    }


def publication(p):
    return {
        "action": "publish",
        "scope": p.approval["scope"],
        "operation_id": str(uuid4()),
        "package_digest": p.package.package_digest,
    }


def test_contract_factory_off_and_shared_native_validation(admitted, tmp_path):
    p = admitted
    with TestClient(create_http_app(tmp_path / "disabled.sqlite")) as client:
        assert client.get(CONTRACT_PATH, headers=p.headers).status_code == 503
    with TestClient(p.app) as client:
        response = client.get(CONTRACT_PATH, headers=p.headers)
        assert response.status_code == 200, response.text
        assert response.json()["contract"] == plugin_admission_contract()
        response = client.post(PATH, headers=p.headers, json=validate_request(p))
        assert response.status_code == 200, response.text
        assert response.json()["packageDigest"] == p.package.package_digest
        assert response.json()["manifestDigest"] == p.package.manifest_digest
        assert p.objects.puts == 0


@pytest.mark.parametrize(
    "change", ["scope", "path", "duplicate", "base64", "manifest", "size", "unknown"]
)
def test_rejected_input_never_publishes(admitted, change):
    p = admitted
    value = validate_request(p)
    if change == "scope":
        value["scope"] = {**value["scope"], "product_id": "other"}
    elif change == "path":
        value["files"][0]["path"] = "../outside"
    elif change == "duplicate":
        value["files"].append(value["files"][0])
    elif change == "base64":
        value["files"][0]["content_base64"] = "!!!"
    elif change == "manifest":
        value["files"][-1]["content_base64"] = base64.b64encode(b"{}").decode()
    elif change == "size":
        value["files"][0]["content_base64"] = base64.b64encode(b"a" * 65537).decode()
    else:
        value["extra"] = True
    with TestClient(p.app) as client:
        assert client.post(PATH, headers=p.headers, json=value).status_code in (403, 422)
    assert p.objects.puts == 0


def test_exact_original_receipt_current_revocation_and_stale_replica(admitted):
    p = admitted
    body = publication(p)
    with TestClient(p.app) as client:
        result = client.post(PATH, headers=p.headers, json=body)
        assert result.status_code == 200, result.text
        original = result.json()["originalResult"]
        assert original["pin"]["package_digest"] == p.package.package_digest
        assert client.post(PATH, headers=p.headers, json=body).json()["originalResult"] == original
        assert p.objects.puts == 1
        conflict = {**body, "package_digest": "sha256:" + "f" * 64}
        assert client.post(PATH, headers=p.headers, json=conflict).status_code == 409
        selector = {**p.headers, "x-runtime-operation": body["operation_id"]}
        assert client.get(PATH, headers=selector).json()["originalResult"] == original
        revoked = {**p.approval, "package_digests": [], "trust_revision": 2}
        write(p.path, revoked)
        p.store.approve(load_plugin_approval(str(p.path), "local").trust, 1)
        # Stale replica still mounting revision 1 cannot serve current approval.
        write(p.path, p.approval)
        assert client.get(PATH, headers=selector).status_code == 403
        write(p.path, revoked)
        current_headers = {**selector, "X-Runtime-Trust-Revision": "2"}
        restored = client.get(PATH, headers=current_headers)
        assert restored.status_code == 200, restored.text
        assert restored.json()["originalResult"] == original
        assert restored.json()["currentApproval"]["approved"] is False
        assert (
            client.post(
                PATH, headers={**p.headers, "X-Runtime-Trust-Revision": "2"}, json=publication(p)
            ).status_code
            == 403
        )
        assert p.objects.puts == 1


def test_same_operation_concurrent_replicas_share_receipt(admitted):
    p = admitted
    body = publication(p)

    def submit(_):
        with TestClient(p.app) as client:
            response = client.post(PATH, headers=p.headers, json=body)
            assert response.status_code == 200, response.text
            return response.json()["originalResult"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(submit, range(2)))
    assert first == second
    assert len(p.objects.values) == 1


@pytest.mark.parametrize("bad", ["cookie", "query", "contract", "token", "selectors"])
def test_transport_and_authority_fail_closed(admitted, bad):
    p = admitted
    headers = dict(p.headers)
    path = PATH
    if bad == "cookie":
        headers["cookie"] = "auth=not-trusted"
    elif bad == "query":
        path += "?product=other"
    elif bad == "contract":
        headers[HEADER] = "sha256:" + "0" * 64
    elif bad == "token":
        headers["Authorization"] = "Bearer " + "rtpa_" + "x" * 43
    else:
        headers["x-runtime-operation"] = str(uuid4())
        headers["x-runtime-plugin-digest"] = p.package.package_digest
    with TestClient(p.app) as client:
        assert client.post(path, headers=headers, json=publication(p)).status_code in (
            400,
            401,
            409,
        )
    assert p.objects.puts == 0


def test_current_digest_query_no_source_or_installation_authority(admitted):
    p = admitted
    with TestClient(p.app) as client:
        result = client.get(
            PATH, headers={**p.headers, "x-runtime-plugin-digest": p.package.package_digest}
        )
        assert result.status_code == 200, result.text
        assert result.json()["currentApproval"]["approved"] is True
        assert "pin" not in result.text
        missing = client.get(PATH, headers={**p.headers, "x-runtime-operation": str(uuid4())})
        assert missing.status_code == 404
        changed = copy.deepcopy(p.approval)
        changed["actions"].remove("plugin.publish")
        changed["trust_revision"] = 2
        write(p.path, changed)
        p.store.approve(load_plugin_approval(str(p.path), "local").trust, 1)
        assert (
            client.post(
                PATH, headers={**p.headers, "X-Runtime-Trust-Revision": "2"}, json=publication(p)
            ).status_code
            == 403
        )
        assert p.objects.puts == 0


def test_large_bounded_skill_package_and_original_bundle_limit(admitted):
    import json

    from agent_core.domain.runtime_bundle_json import load_bundle_json

    p = admitted
    manifest = {
        "manifest_version": "0.2",
        "id": "large-package",
        "version": "1.0.0",
        "publisher": "Test",
        "components": [{"id": "demo", "kind": "skill-bundle", "skill_root": "content/demo"}],
    }
    contents = {
        "plugin.json": json.dumps(manifest).encode(),
        "README.md": b"Bounded package requiring more than the Bundle JSON envelope",
        "content/demo/SKILL.md": (
            b"---\nname: demo\ndescription: Demo guide\n---\nRead references\n"
        ),
        **{
            f"content/demo/references/data-{i}.txt": b"".join(
                hashlib.sha256(f"{i}-{j}".encode()).hexdigest().encode() for j in range(625)
            )
            for i in range(8)
        },
    }
    request = {
        "action": "validate",
        "scope": p.approval["scope"],
        "files": [
            {"path": name, "content_base64": base64.b64encode(value).decode()}
            for name, value in sorted(contents.items())
        ],
    }
    raw = json.dumps(request).encode()
    assert 262144 < len(raw) < 1500000
    with pytest.raises(ValueError, match="invalid JSON bytes"):
        load_bundle_json(raw)  # Existing Runtime Bundle limits must not widen.
    with TestClient(p.app) as client:
        response = client.post(
            PATH, headers={**p.headers, "Content-Type": "application/json"}, content=raw
        )
        assert response.status_code == 200, response.text
        assert response.json()["manifest"]["id"] == "large-package"
    assert p.objects.puts == 0


def test_product_target_has_one_shared_catalog_identity(admitted):
    from zebra_agent_api.plugin_admission_config import PluginAdmissionApproval

    p = admitted
    first = load_plugin_approval(str(p.path), "local")
    rotated = PluginAdmissionApproval.model_validate(
        {
            **p.approval,
            "credential_sha256": "a" * 64,
            "trust_revision": 2,
        }
    )
    assert first.actor == rotated.actor
    assert first.trust.fingerprint != rotated.trust.fingerprint
    with pytest.raises(ValueError):
        PluginAdmissionApproval.model_validate({**p.approval, "actor": "plugin-bypass"})
