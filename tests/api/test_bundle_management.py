"""Scoped pure native validation transport; no execution or persistence."""

from pathlib import Path

from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app

from tests.test_bundle_assembly import settings

CONTRACT_PATH = "/management/v1/bundle-contract"
VALIDATION_PATH = "/management/v1/bundle-validation"
TOKEN = "rtbv_" + "a" * 43
HEADERS = {
    "Authorization": "Bearer " + TOKEN,
    "X-Runtime-Deployment": "runtime-a",
    "X-Runtime-Audience": "management-a",
    "X-Runtime-Product": "product-a",
    "X-Runtime-Environment": "dev",
    "X-Runtime-Trust-Revision": "1",
}


def test_disabled_validation_has_fixed_unavailable_response(tmp_path: Path) -> None:
    with TestClient(create_http_app(tmp_path / "state.sqlite", settings=settings())) as client:
        response = client.get(CONTRACT_PATH, headers=HEADERS)
    assert response.status_code == 503
    assert response.json() == {"error": {"code": "MANAGEMENT_UNAVAILABLE"}}
    assert response.headers["cache-control"] == "no-store"


def write(path, value):
    import json

    temporary = path.with_suffix(".new")
    temporary.write_text(json.dumps(value))
    temporary.chmod(0o600)
    temporary.replace(path)


def configured_fixture(tmp_path):
    import hashlib
    from dataclasses import replace

    from agent_core.domain.runtime_bundle_json import json_digest

    from tests.test_bundle_assembly import approved_assembly

    original = settings()
    assembly, catalog = approved_assembly(original)
    candidate = assembly.bundle.model_dump(mode="json")
    candidate["manifest"]["scope"]["namespace_id"] = "local"
    candidate["bundle_digest"] = json_digest(candidate["manifest"])
    catalog["scope"] = candidate["manifest"]["scope"]
    approval = {
        "schema_version": "cloud-agent.bundle-management-approval/1",
        "scope": catalog["scope"],
        "audience": "management-a",
        "trust_revision": 1,
        "credential_sha256": hashlib.sha256(TOKEN.encode()).hexdigest(),
        "expires_at": "2099-01-01T00:00:00Z",
        "actions": ["bundle.contract.read", "bundle.validate"],
    }
    path = tmp_path / "approval.json"
    catalog_path = tmp_path / "catalog.json"
    write(path, approval)
    write(catalog_path, catalog)
    configured = replace(
        original, bundle_management_config=str(path), runtime_bundle_config=str(catalog_path)
    )
    headers = {
        **HEADERS,
        "X-Runtime-Deployment": catalog["scope"]["deployment_id"],
        "X-Runtime-Environment": catalog["scope"]["environment"],
    }
    return configured, path, approval, candidate, headers


def test_real_contract_and_validation_bind_exact_native_assembly(tmp_path):
    from agent_core.domain.runtime_bundle import parse_runtime_bundle
    from agent_core.domain.runtime_bundle_json import json_digest
    from zebra_agent_config.bundle_settings import load_execution_catalog

    configured, _, approval, candidate, headers = configured_fixture(tmp_path)
    with TestClient(create_http_app(tmp_path / "state.sqlite", settings=configured)) as client:
        response = client.get(CONTRACT_PATH, headers=headers)
        assert response.status_code == 200
        description = response.json()
        contract = description["contract"]
        digest = description["contractDigest"]
        assert digest == contract["contractDigest"]
        assert digest == json_digest({k: v for k, v in contract.items() if k != "contractDigest"})
        assert description["scope"] == approval["scope"]
        assert contract["transport"]["maxBundleBytes"] == 262144
        import json

        raw = json.dumps(candidate).encode()
        response = client.post(
            VALIDATION_PATH,
            headers={**headers, "X-Runtime-Bundle-Contract": digest},
            content=raw,
        )
        assert response.status_code == 400  # Explicit JSON MIME required.
        response = client.post(
            VALIDATION_PATH,
            headers={**headers, "X-Runtime-Bundle-Contract": digest},
            json=candidate,
        )
        assert response.status_code == 200
        body = response.json()
        catalog = load_execution_catalog(configured.runtime_bundle_config)
        assert body["bundleDigest"] == candidate["bundle_digest"]
        assert body["assemblyDigest"] == catalog.resolve(parse_runtime_bundle(raw)).assembly_digest
        assert body["approvalDigest"] == json_digest(catalog.model_dump(mode="json"))
        assert body["checks"] == {
            "bundle": "passed",
            "assetApproval": "passed",
            "worker": "not_checked",
            "publication": "not_performed",
        }
        assert body["scope"] == approval["scope"] and body["trustRevision"] == 1
        assert body["contractDigest"] == digest
        assert response.headers["cache-control"] == "no-store"
        assert all(secret not in response.text for secret in (TOKEN, "baseline_key", "ab" * 32))


def test_authority_is_separate_exact_and_action_scoped(tmp_path):
    configured, path, approval, candidate, headers = configured_fixture(tmp_path)
    with TestClient(create_http_app(tmp_path / "state.sqlite", settings=configured)) as client:
        digest = client.get(CONTRACT_PATH, headers=headers).json()["contractDigest"]
        request_headers = {**headers, "X-Runtime-Bundle-Contract": digest}
        for token in (
            "private-token",
            "operator-token",
            "rtmg_" + "a" * 43,
            "rthm_" + "a" * 43,
            TOKEN[:-1] + "b",
        ):
            result = client.get(
                CONTRACT_PATH, headers={**headers, "Authorization": "Bearer " + token}
            )
            assert result.status_code == 401
            assert result.json() == {"error": {"code": "UNAUTHENTICATED"}}
        for header in headers.keys() - {"Authorization"}:
            response = client.get(CONTRACT_PATH, headers={**headers, header: "wrong"})
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "SCOPE_MISMATCH"
        write(path, {**approval, "actions": ["bundle.contract.read"]})
        assert (
            client.post(VALIDATION_PATH, headers=request_headers, json=candidate).status_code == 403
        )
        write(path, {**approval, "actions": ["bundle.validate"]})
        assert client.get(CONTRACT_PATH, headers=headers).status_code == 403
        assert (
            client.post(VALIDATION_PATH, headers=request_headers, json=candidate).status_code == 200
        )
        write(path, {**approval, "expires_at": "2000-01-01T00:00:00Z"})
        assert (
            client.post(VALIDATION_PATH, headers=request_headers, json=candidate).status_code == 403
        )
        path.unlink()
        assert client.get(CONTRACT_PATH, headers=headers).status_code == 503


def test_transport_rejects_ambiguous_headers_body_and_methods(tmp_path):
    configured, _, _, candidate, headers = configured_fixture(tmp_path)
    with TestClient(create_http_app(tmp_path / "state.sqlite", settings=configured)) as client:
        digest = client.get(CONTRACT_PATH, headers=headers).json()["contractDigest"]
        post_headers = {
            **headers,
            "X-Runtime-Bundle-Contract": digest,
            "Content-Type": "application/json",
        }
        for path, allowed in ((CONTRACT_PATH, "GET"), (VALIDATION_PATH, "POST")):
            for method in {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE"} - {
                allowed
            }:
                response = client.request(method, path, headers=post_headers)
                assert response.status_code == 405
                assert response.headers["allow"] == allowed
            for extra in ({"Cookie": "x=y"}, {"Content-Encoding": "gzip"}):
                response = client.request(
                    allowed, path, headers={**post_headers, **extra}, content="{}"
                )
                assert response.status_code == 400
            assert client.request(allowed, path + "?x=1", headers=post_headers).status_code == 400
        for name in (
            "Authorization",
            *headers.keys() - {"Authorization"},
            "Content-Type",
            "X-Runtime-Bundle-Contract",
            "Content-Length",
        ):
            duplicate = [*post_headers.items(), (name, post_headers.get(name, "2"))]
            if name == "Content-Length":
                duplicate.append((name, "2"))
            response = client.post(VALIDATION_PATH, headers=duplicate, content="{}")
            assert response.status_code in (400, 401, 403)
        assert (
            client.request("GET", CONTRACT_PATH, headers=headers, content="{}").status_code == 400
        )
        assert client.post(VALIDATION_PATH, headers=headers, json=candidate).status_code == 400
        assert (
            client.post(
                VALIDATION_PATH,
                headers={**post_headers, "X-Runtime-Bundle-Contract": "sha256:" + "0" * 64},
                json=candidate,
            ).status_code
            == 409
        )
        assert (
            client.post(VALIDATION_PATH, headers=post_headers, content=b" " * 262145).status_code
            == 400
        )


def test_hostile_json_native_semantic_scope_and_asset_negatives(tmp_path):
    import copy

    from agent_core.domain.runtime_bundle_json import json_digest

    configured, _, _, candidate, headers = configured_fixture(tmp_path)
    with TestClient(create_http_app(tmp_path / "state.sqlite", settings=configured)) as client:
        digest = client.get(CONTRACT_PATH, headers=headers).json()["contractDigest"]
        post_headers = {
            **headers,
            "X-Runtime-Bundle-Contract": digest,
            "Content-Type": "application/json",
        }
        for raw in (
            b'{"x":1,"x":2}',
            b'{"x":NaN}',
            b'{"x":1.0}',
            b"\xef\xbb\xbf{}",
            b'{"x":"\\ud800"}',
            b"[" * 30 + b"0" + b"]" * 30,
        ):
            response = client.post(VALIDATION_PATH, headers=post_headers, content=raw)
            assert response.status_code == 422
            assert response.json() == {"error": {"code": "BUNDLE_REJECTED"}}
        for field in candidate["manifest"]["scope"]:
            altered = copy.deepcopy(candidate)
            altered["manifest"]["scope"][field] = (
                "https://other.example" if field == "authority_issuer" else "other"
            )
            altered["bundle_digest"] = json_digest(altered["manifest"])
            assert (
                client.post(VALIDATION_PATH, headers=post_headers, json=altered).status_code == 403
            )
        for change in ("model", "thinking", "closure", "digest", "asset"):
            altered = copy.deepcopy(candidate)
            params = altered["manifest"]["domains"]["model"]["parameters"]
            if change == "model":
                params["model"] = "unapproved"
            elif change == "thinking":
                params["thinking"] = "enabled"
            elif change == "closure":
                altered["manifest"]["lock"].pop()
            elif change == "asset":
                altered["manifest"]["engine"]["image"]["digest"] = "sha256:" + "0" * 64
                for pin in altered["manifest"]["lock"]:
                    if pin["kind"] == "image":
                        pin["digest"] = "sha256:" + "0" * 64
            altered["bundle_digest"] = (
                "sha256:" + "0" * 64 if change == "digest" else json_digest(altered["manifest"])
            )
            assert (
                client.post(VALIDATION_PATH, headers=post_headers, json=altered).status_code == 422
            )


def test_declared_body_length_must_match_received_bytes(tmp_path):
    configured, _, _, candidate, headers = configured_fixture(tmp_path)
    with TestClient(create_http_app(tmp_path / "state.sqlite", settings=configured)) as client:
        digest = client.get(CONTRACT_PATH, headers=headers).json()["contractDigest"]
        response = client.post(
            VALIDATION_PATH,
            headers={**headers, "X-Runtime-Bundle-Contract": digest, "Content-Length": "0"},
            json=candidate,
        )
        assert response.status_code == 400
        assert response.json() == {"error": {"code": "INVALID_ARGUMENT"}}


def test_unlisted_http_methods_have_same_fixed_error(tmp_path):
    configured, _, _, _, headers = configured_fixture(tmp_path)
    with TestClient(create_http_app(tmp_path / "state.sqlite", settings=configured)) as client:
        for path in (CONTRACT_PATH, VALIDATION_PATH):
            response = client.request("PROPFIND", path, headers=headers)
            assert response.status_code == 405
            assert response.json() == {"error": {"code": "METHOD_NOT_ALLOWED"}}
            assert response.headers["cache-control"] == "no-store"


def isolated_app(configured):
    from fastapi import FastAPI
    from zebra_agent_api.bundle_management import register_bundle_management

    app = FastAPI()
    register_bundle_management(app, configured, "local")
    return app


def test_body_slots_cover_both_routes_and_slow_body_is_bounded(tmp_path, monkeypatch):
    import asyncio

    import httpx
    from zebra_agent_api import bundle_management as module
    from zebra_agent_api.bundle_management_contract import bundle_contract_digest

    assert module.BODY_TIMEOUT == 0.2
    monkeypatch.setattr(module, "BODY_TIMEOUT", 0.05)
    configured, _, _, _, headers = configured_fixture(tmp_path)
    app = isolated_app(configured)
    post_headers = {
        **headers,
        "Content-Type": "application/json",
        "X-Runtime-Bundle-Contract": bundle_contract_digest(),
    }

    async def check():
        started = 0

        async def slow_body():
            nonlocal started
            started += 1
            yield b"{"
            await asyncio.sleep(2)
            yield b"}"

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://test"
        ) as client:
            requests = [
                asyncio.create_task(
                    client.post(VALIDATION_PATH, headers=post_headers, content=slow_body())
                )
                for _ in range(8)
            ]
            while started != 8:
                await asyncio.sleep(0.001)
            response = await client.get(CONTRACT_PATH, headers=headers)
            assert response.status_code == 429 and response.headers["retry-after"] == "1"
            results = await asyncio.gather(*requests)
            assert all(
                r.status_code == 400 and r.json() == {"error": {"code": "INVALID_ARGUMENT"}}
                for r in results
            )
            assert (await client.get(CONTRACT_PATH, headers=headers)).status_code == 200

    asyncio.run(check())


def test_timeout_and_cancel_keep_actual_thread_slots_and_consume_late_errors(tmp_path, monkeypatch):
    import asyncio
    import threading

    import httpx
    from zebra_agent_api import bundle_management as module
    from zebra_agent_api.bundle_management_contract import bundle_contract_digest

    assert module.REQUEST_TIMEOUT == 1.0
    configured, _, _, candidate, headers = configured_fixture(tmp_path)
    original = module.load_bundle_management_approval
    post_headers = {**headers, "X-Runtime-Bundle-Contract": bundle_contract_digest()}
    for cancel in (False, True):
        release = threading.Event()
        started = []

        def blocked(*args, started=started, release=release):
            started.append(1)
            release.wait(5)
            raise ValueError("late-private-error")

        monkeypatch.setattr(module, "load_bundle_management_approval", blocked)
        monkeypatch.setattr(module, "REQUEST_TIMEOUT", 2.0 if cancel else 0.05)
        app = isolated_app(configured)

        async def check(cancel=cancel, release=release, started=started, app=app):
            contexts = []
            asyncio.get_running_loop().set_exception_handler(
                lambda _loop, context: contexts.append(context)
            )
            try:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="https://test"
                ) as client:
                    tasks = [
                        asyncio.create_task(
                            client.get(CONTRACT_PATH, headers=headers)
                            if index % 2
                            else client.post(VALIDATION_PATH, headers=post_headers, json=candidate)
                        )
                        for index in range(8)
                    ]
                    while len(started) != 8:
                        await asyncio.sleep(0.001)
                    if cancel:
                        for task in tasks:
                            task.cancel()
                        results = await asyncio.gather(*tasks, return_exceptions=True)
                        assert all(isinstance(result, asyncio.CancelledError) for result in results)
                    else:
                        responses = await asyncio.gather(*tasks)
                        assert all(response.status_code == 503 for response in responses)
                        assert all("private" not in response.text for response in responses)
                    for path in (CONTRACT_PATH, VALIDATION_PATH):
                        response = await client.request(
                            "GET" if path == CONTRACT_PATH else "POST",
                            path,
                            headers=post_headers,
                            json=candidate if path == VALIDATION_PATH else None,
                        )
                        assert response.status_code == 429
                        assert response.headers["retry-after"] == "1"
                    release.set()
                    monkeypatch.setattr(module, "load_bundle_management_approval", original)
                    await asyncio.sleep(0.03)
                    assert (await client.get(CONTRACT_PATH, headers=headers)).status_code == 200
                    assert contexts == []
            finally:
                release.set()
                await asyncio.sleep(0.01)

        asyncio.run(check())


def test_full_approval_is_reauthorized_immediately_before_response(tmp_path, monkeypatch):
    import asyncio
    import copy
    import threading

    import httpx
    from zebra_agent_api import bundle_management as module
    from zebra_agent_api.bundle_management_contract import bundle_contract_digest
    from zebra_agent_config.bundle_settings import RuntimeExecutionCatalog

    configured, path, approval, candidate, headers = configured_fixture(tmp_path)
    post_headers = {**headers, "X-Runtime-Bundle-Contract": bundle_contract_digest()}
    original_resolve = RuntimeExecutionCatalog.resolve
    original_contract = module.native_bundle_contract
    for method in ("GET", "POST"):
        changes = [
            {"scope": {**approval["scope"], "target_id": "other-target"}},
            {"scope": {**approval["scope"], "authority_issuer": "https://other.example"}},
            {"expires_at": "2098-01-01T00:00:00Z"},
            {"expires_at": "2000-01-01T00:00:00Z"},
            {"actions": ["bundle.contract.read"] if method == "POST" else ["bundle.validate"]},
            {"actions": list(reversed(approval["actions"]))},
            {"credential_sha256": "0" * 64},
            {"trust_revision": 2},
        ]
        for change in changes:
            write(path, approval)
            entered, release = threading.Event(), threading.Event()

            def blocked_contract(entered=entered, release=release):
                entered.set()
                release.wait(5)
                return original_contract()

            def blocked_resolve(catalog, bundle, entered=entered, release=release):
                entered.set()
                release.wait(5)
                return original_resolve(catalog, bundle)

            monkeypatch.setattr(
                module,
                "native_bundle_contract",
                blocked_contract if method == "GET" else original_contract,
            )
            monkeypatch.setattr(
                RuntimeExecutionCatalog,
                "resolve",
                blocked_resolve if method == "POST" else original_resolve,
            )

            async def check(method=method, entered=entered, release=release, change=change):
                try:
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=isolated_app(configured)),
                        base_url="https://test",
                    ) as client:
                        task = asyncio.create_task(
                            client.get(CONTRACT_PATH, headers=headers)
                            if method == "GET"
                            else client.post(VALIDATION_PATH, headers=post_headers, json=candidate)
                        )
                        while not entered.is_set():
                            await asyncio.sleep(0.001)
                        write(path, {**copy.deepcopy(approval), **change})
                        release.set()
                        response = await task
                        assert response.status_code in (401, 403)
                        assert response.json()["error"]["code"] in {
                            "UNAUTHENTICATED",
                            "PERMISSION_DENIED",
                            "SCOPE_MISMATCH",
                        }
                finally:
                    release.set()

            asyncio.run(check())


def test_concurrent_validation_receipts_are_isolated_and_catalog_scope_is_exact(tmp_path):
    import asyncio
    import copy
    import json

    import httpx
    from agent_core.domain.runtime_bundle_json import json_digest
    from zebra_agent_api.bundle_management_contract import bundle_contract_digest

    configured, _, _, candidate, headers = configured_fixture(tmp_path)
    second = copy.deepcopy(candidate)
    second["manifest"]["domains"]["instructions"]["parameters"]["business_text"] = (
        "Independent candidate"
    )
    second["bundle_digest"] = json_digest(second["manifest"])
    post_headers = {**headers, "X-Runtime-Bundle-Contract": bundle_contract_digest()}
    app = isolated_app(configured)
    before = {path: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://test"
        ) as client:
            responses = await asyncio.gather(
                *(
                    client.post(VALIDATION_PATH, headers=post_headers, json=value)
                    for value in (candidate, second)
                )
            )
            assert all(response.status_code == 200 for response in responses)
            first, last = [response.json() for response in responses]
            assert first["bundleDigest"] == candidate["bundle_digest"]
            assert last["bundleDigest"] == second["bundle_digest"]
            assert first["assemblyDigest"] != last["assemblyDigest"]
            assert first["approvalDigest"] == last["approvalDigest"]
            assert first["checks"]["worker"] == "not_checked"

    asyncio.run(check())
    assert {path: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()} == before
    path = Path(configured.runtime_bundle_config)
    catalog = json.loads(path.read_bytes())
    catalog["scope"]["target_id"] = "different-target"
    write(path, catalog)
    with TestClient(app) as client:
        response = client.post(VALIDATION_PATH, headers=post_headers, json=candidate)
        assert response.status_code == 403
        assert response.json() == {"error": {"code": "SCOPE_MISMATCH"}}
