"""Pure script closure validation: real domain/catalog, no execution or DB writes."""

import copy
import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest
from agent_core.domain.runtime_bundle_json import json_digest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app
from zebra_agent_api.script_bundle_contract import (
    CONTRACT_PATH as GET,
)
from zebra_agent_api.script_bundle_contract import (
    VALIDATION_PATH as POST,
)
from zebra_agent_api.script_bundle_contract import (
    native_script_bundle_contract,
)
from zebra_agent_config.bundle_settings import load_execution_catalog

from tests.agent_core.test_native_script_binding import binding, plan, script
from tests.api.test_bundle_management import configured_fixture as base_fixture
from tests.api.test_bundle_management import write
from tests.api.test_bundle_management_process import row_counts


@pytest.fixture
def prepared(tmp_path):
    return configured_fixture(tmp_path)


def configured_fixture(tmp_path):
    cfg, approval_path, approval, base, headers = base_fixture(tmp_path)
    marker = tmp_path / "MUST_NOT_EXECUTE"
    source = (
        f"open({str(marker)!r}, 'w').write('executed')\n"
        "def execute(arguments):\n    return {'value':'ok'}\n"
    )
    native = script(source=source)
    selected = plan(binding(source=source))
    value = {
        "schema_version": "cloud-agent.script-bundle/1",
        "base_bundle": base,
        "scripts": selected.model_dump(mode="json"),
    }
    value["bundle_digest"] = json_digest(value)
    catalog_path = Path(cfg.runtime_bundle_config)
    catalog = json.loads(catalog_path.read_bytes())
    catalog.update(
        schema_version="cloud-agent.execution-catalog/2",
        script_plans=[selected.model_dump(mode="json")],
        scripts=[native.manifest.model_dump(mode="json") | {"source": source}],
    )
    write(catalog_path, catalog)
    approval["actions"] += ["script-bundle.contract.read", "script-bundle.validate"]
    write(approval_path, approval)
    headers = headers | {
        "Content-Type": "application/json",
        "X-Runtime-Script-Bundle-Contract": native_script_bundle_contract()["contractDigest"],
    }
    return cfg, approval_path, approval, value, headers


def test_exact_observation_no_execution_or_mutation(prepared, tmp_path):
    cfg, approval_path, _, value, headers = prepared
    db = tmp_path / "state.sqlite"
    catalog_before = Path(cfg.runtime_bundle_config).read_bytes()
    approval_before = approval_path.read_bytes()
    with TestClient(create_http_app(db, settings=cfg)) as client:
        discovery = client.get(GET, headers=headers)
        assert discovery.status_code == 200, discovery.text
        assert discovery.json()["contract"] == native_script_bundle_contract()
        before = row_counts(db)
        raw = json.dumps(value, indent=1).encode()
        response = client.post(POST, headers=headers, content=raw)
        assert response.status_code == 200, response.text
        result = response.json()
        catalog = load_execution_catalog(cfg.runtime_bundle_config)
        from agent_core.domain.script_bundle import ScriptBundle

        assembly = catalog.resolve_scripts(ScriptBundle.model_validate(value))
        assert result["inputDigest"] == "sha256:" + sha256(raw).hexdigest()
        assert result["scriptBundleDigest"] == value["bundle_digest"]
        assert result["baseBundleDigest"] == value["base_bundle"]["bundle_digest"]
        assert result["assemblyDigest"] == assembly.assembly_digest
        assert result["approvalDigest"] == json_digest(catalog.model_dump(mode="json"))
        assert result["checks"] == native_script_bundle_contract()["checks"]
        assert result["capabilities"]["persistence"] == "not_performed"
        assert result["capabilities"]["coverageAuthority"] is False
        assert "MUST_NOT_EXECUTE" not in response.text and '"source":' not in response.text
        assert row_counts(db) == before
    assert not (tmp_path / "MUST_NOT_EXECUTE").exists()
    assert approval_path.read_bytes() == approval_before
    assert Path(cfg.runtime_bundle_config).read_bytes() == catalog_before


def test_old_actions_never_implicitly_allow_scripts_and_old_route_unchanged(prepared, tmp_path):
    cfg, path, approval, value, headers = prepared
    write(path, approval | {"actions": ["bundle.contract.read", "bundle.validate"]})
    with TestClient(create_http_app(tmp_path / "state.sqlite", settings=cfg)) as client:
        assert client.get(GET, headers=headers).status_code == 403
        assert client.post(POST, headers=headers, json=value).status_code == 403
        response = client.get("/management/v1/bundle-contract", headers=headers)
        assert response.status_code == 200
        old = headers | {"X-Runtime-Bundle-Contract": response.json()["contractDigest"]}
        assert (
            client.post(
                "/management/v1/bundle-validation", headers=old, json=value["base_bundle"]
            ).status_code
            == 200
        )
        assert (
            client.post("/management/v1/bundle-validation", headers=old, json=value).status_code
            == 422
        )


@pytest.mark.parametrize("case", ["digest", "lock", "plan", "source-field", "base-only", "scope"])
def test_hostile_or_unapproved_bundle(prepared, tmp_path, case):
    cfg, _, _, original, headers = prepared
    value = copy.deepcopy(original)
    if case == "digest":
        value["bundle_digest"] = "sha256:" + "0" * 64
    elif case == "lock":
        value["scripts"]["lock"].pop()
    elif case == "plan":
        value["scripts"]["runner"]["python"] = "/unapproved/python"
    elif case == "source-field":
        value["source"] = "DO_NOT_ECHO"
    elif case == "base-only":
        value = value["base_bundle"]
    else:
        value["base_bundle"]["manifest"]["scope"]["product_id"] = "foreign"
        value["base_bundle"]["bundle_digest"] = json_digest(value["base_bundle"]["manifest"])
    if case not in {"digest", "base-only"}:
        value["bundle_digest"] = json_digest(
            {k: v for k, v in value.items() if k != "bundle_digest"}
        )
    with TestClient(create_http_app(tmp_path / "state.sqlite", settings=cfg)) as c:
        response = c.post(POST, headers=headers, json=value)
        assert response.status_code == (403 if case == "scope" else 422), response.text
        assert "DO_NOT_ECHO" not in response.text


def test_scope_tokens_contract_transport_and_catalog_refusal(prepared, tmp_path):
    cfg, _, _, value, headers = prepared
    with TestClient(create_http_app(tmp_path / "state.sqlite", settings=cfg)) as c:
        for prefix in ("rtsv_", "rtpub_", "mg_access_"):
            assert (
                c.get(
                    GET, headers=headers | {"Authorization": "Bearer " + prefix + "a" * 43}
                ).status_code
                == 401
            )
        assert c.get(GET, headers=headers | {"X-Runtime-Product": "foreign"}).status_code == 403
        assert (
            c.post(
                POST, headers=headers | {"X-Runtime-Script-Bundle-Contract": "bad"}, json=value
            ).status_code
            == 409
        )
        assert (
            c.post(POST, headers=headers | {"Cookie": "no=authority"}, json=value).status_code
            == 400
        )
        assert c.get(GET + "?unexpected=1", headers=headers).status_code == 400
        assert c.post(GET, headers=headers, json=value).status_code == 405
        assert c.post(POST, headers=headers, content=b"x" * 262145).status_code == 400
        assert (
            c.post(
                POST, headers=headers, content='{"bundle_digest":1,"bundle_digest":2}'
            ).status_code
            == 422
        )
        catalog = json.loads(Path(cfg.runtime_bundle_config).read_bytes())
        catalog.pop("script_plans")
        catalog.pop("scripts")
        catalog["schema_version"] = "cloud-agent.execution-catalog/1"
        write(Path(cfg.runtime_bundle_config), catalog)
        assert c.post(POST, headers=headers, json=value).status_code == 422
        Path(cfg.runtime_bundle_config).write_text("invalid private JSON")
        response = c.post(POST, headers=headers, json=value)
        assert response.status_code == 503 and "private JSON" not in response.text


@pytest.mark.parametrize("changed", ["authority", "catalog"])
def test_late_revocation_never_promotes_observation(prepared, tmp_path, monkeypatch, changed):
    from zebra_agent_config.native_script import ScriptExecutionCatalog

    cfg, path, approval, value, headers = prepared
    resolve = ScriptExecutionCatalog.resolve_scripts

    def revoke(self, bundle):
        result = resolve(self, bundle)
        if changed == "authority":
            write(path, approval | {"actions": ["script-bundle.contract.read"]})
        else:
            catalog = json.loads(Path(cfg.runtime_bundle_config).read_bytes())
            catalog["script_plans"][0]["runner"]["python"] = "/changed/python"
            write(Path(cfg.runtime_bundle_config), catalog)
        return result

    monkeypatch.setattr(ScriptExecutionCatalog, "resolve_scripts", revoke)
    with TestClient(create_http_app(tmp_path / "state.sqlite", settings=cfg)) as c:
        assert c.post(POST, headers=headers, json=value).status_code == 403


def test_mounted_discovery_works_for_new_and_old_protocols(prepared, tmp_path):
    cfg, _, _, _, headers = prepared
    outer = FastAPI()
    outer.mount("/native", create_http_app(tmp_path / "state.sqlite", settings=cfg))
    with TestClient(outer) as c:
        for path in (GET, "/management/v1/bundle-contract"):
            assert c.get("/native" + path, headers=headers).status_code == 200


def test_unconfigured_is_fail_closed(tmp_path):
    from tests.test_bundle_assembly import settings

    with TestClient(
        create_http_app(
            tmp_path / "state.sqlite", settings=replace(settings(), bundle_management_config=None)
        )
    ) as c:
        assert c.get(GET, headers={"Authorization": "Bearer rtbv_" + "a" * 43}).status_code == 503


def test_timed_out_threads_keep_bounded_slots(prepared, tmp_path, monkeypatch):
    import asyncio
    import threading

    import httpx
    from zebra_agent_config.native_script import ScriptExecutionCatalog

    cfg, _, _, value, headers = prepared
    entered, release = threading.Event(), threading.Event()
    lock = threading.Lock()
    count = 0
    original = ScriptExecutionCatalog.resolve_scripts

    def blocked(self, bundle):
        nonlocal count
        with lock:
            count += 1
            if count == 8:
                entered.set()
        assert release.wait(10), "owned test release deadline"
        return original(self, bundle)

    monkeypatch.setattr(ScriptExecutionCatalog, "resolve_scripts", blocked)

    async def run():
        app = create_http_app(tmp_path / "state.sqlite", settings=cfg)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            tasks = [
                asyncio.create_task(c.post(POST, headers=headers, json=value)) for _ in range(8)
            ]
            try:
                assert await asyncio.to_thread(entered.wait, 5)
                replies = await asyncio.gather(*tasks)
                assert all(reply.status_code == 503 for reply in replies)
                response = await c.get(GET, headers=headers)
                assert response.status_code == 429
            finally:
                release.set()
                await asyncio.gather(*tasks, return_exceptions=True)
            for _ in range(100):
                if (await c.get(GET, headers=headers)).status_code == 200:
                    break
                await asyncio.sleep(0.02)
            else:
                raise AssertionError("retained slots did not release")

    asyncio.run(run())


def test_mounted_package_validation_discovery_uses_same_fixed_transport(tmp_path):
    from tests.api.test_script_validation import configured_fixture as package_fixture

    cfg, _, _, _, headers = package_fixture(tmp_path)
    outer = FastAPI()
    outer.mount("/native", create_http_app(tmp_path / "c.sqlite", settings=cfg))
    with TestClient(outer) as c:
        response = c.get("/native/management/v1/script-contract", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["contractVersion"] == "script-validation/1"
