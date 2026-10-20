from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings, load_settings

TOKEN = "rtmg_" + "a" * 43
PATH = "/management/v1/target"
HEADERS = {
    "Authorization": "Bearer " + TOKEN,
    "X-Runtime-Deployment": "runtime-a",
    "X-Runtime-Audience": "management-a",
    "X-Runtime-Product": "a",
    "X-Runtime-Environment": "dev",
    "X-Runtime-Trust-Revision": "1",
}


def configuration() -> dict[str, object]:
    return {
        "deploymentId": "runtime-a",
        "deploymentNamespace": "local",
        "audience": "management-a",
        "productId": "a",
        "environment": "dev",
        "trustRevision": 1,
        "credentialSha256": hashlib.sha256(TOKEN.encode()).hexdigest(),
        "expiresAt": "2099-01-01T00:00:00Z",
        "actions": ["target.describe"],
    }


def write(path: Path, value: dict[str, object]) -> None:
    temporary = path.with_suffix(".new")
    temporary.write_text(json.dumps(value))
    temporary.chmod(0o600)
    temporary.replace(path)


def settings(path: Path | None) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=":memory:",
        api=ApiSettings(auth_token="old-api-token"),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test",
        ),
        platform_operator_token="operator-token",
        runtime_management_config=str(path) if path else None,
    )


def test_real_http_descriptor_and_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "management.json"
    write(path, configuration())
    app = create_http_app(tmp_path / "sessions.sqlite", settings=settings(path))
    with TestClient(app) as client:
        response = client.get(PATH, headers=HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert body["contractVersion"] == "runtime-management/1"
        assert body["deploymentId"] == "runtime-a"
        assert body["checks"] == {"database": "not_checked", "worker": "not_checked"}
        assert body["capabilities"] == {
            "bundleManagement": "unsupported",
            "nativeScriptAbi": "unsupported",
        }
        assert response.headers["cache-control"] == "no-store"
        assert TOKEN not in response.text and "credentialSha256" not in response.text
        for token in ("", "old-api-token", "operator-token", "mg_access_x", TOKEN[:-1] + "b"):
            assert (
                client.get(
                    PATH, headers={**HEADERS, "Authorization": "Bearer " + token}
                ).status_code
                == 401
            )
        for header in HEADERS.keys() - {"Authorization"}:
            assert client.get(PATH, headers={**HEADERS, header: "wrong"}).status_code == 403
        for method in ("POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
            assert client.request(method, PATH, headers=HEADERS).status_code == 405
        assert client.get(PATH + "?endpoint=https://untrusted", headers=HEADERS).status_code == 400
        assert client.request("GET", PATH, headers=HEADERS, content="{}").status_code == 400
        assert (
            client.request(
                "GET", PATH, headers={**HEADERS, "Content-Length": "0"}, content="unframed"
            ).status_code
            == 400
        )
        assert (
            client.get(
                PATH, headers=[*HEADERS.items(), ("Authorization", "Bearer " + TOKEN)]
            ).status_code
            == 401
        )
        # Rotation/revocation is reread per request, not process-cached.
        value = configuration()
        value["credentialSha256"] = "b" * 64
        write(path, value)
        assert client.get(PATH, headers=HEADERS).status_code == 401
        value = configuration()
        value["expiresAt"] = "2000-01-01T00:00:00Z"
        write(path, value)
        assert client.get(PATH, headers=HEADERS).status_code == 401
        path.unlink()
        assert client.get(PATH, headers=HEADERS).status_code == 503


@pytest.mark.parametrize(
    "mutation",
    [
        {"extra": "untrusted"},
        {"trustRevision": True},
        {"trustRevision": 0},
        {"actions": ["host.write"]},
        {"deploymentNamespace": "other"},
        {"expiresAt": "not-a-date"},
        {"credentialSha256": "raw-secret"},
    ],
)
def test_invalid_configuration(tmp_path: Path, mutation: dict[str, object]) -> None:
    path = tmp_path / "management.json"
    write(path, {**configuration(), **mutation})
    with TestClient(
        create_http_app(tmp_path / "sessions.sqlite", settings=settings(path))
    ) as client:
        response = client.get(PATH, headers=HEADERS)
        assert response.status_code == 503
        assert "untrusted" not in response.text and "raw-secret" not in response.text


def test_shared_configuration_two_apps_and_private_file(tmp_path: Path) -> None:
    path = tmp_path / "management.json"
    write(path, configuration())
    with (
        TestClient(create_http_app(tmp_path / "a.sqlite", settings=settings(path))) as first,
        TestClient(create_http_app(tmp_path / "b.sqlite", settings=settings(path))) as second,
    ):
        assert (
            first.get(PATH, headers=HEADERS).status_code
            == second.get(PATH, headers=HEADERS).status_code
            == 200
        )
        value = configuration()
        value["trustRevision"] = 2
        write(path, value)
        assert (
            first.get(PATH, headers=HEADERS).status_code
            == second.get(PATH, headers=HEADERS).status_code
            == 403
        )
        new_headers = {**HEADERS, "X-Runtime-Trust-Revision": "2"}
        assert second.get(PATH, headers=new_headers).json()["trustRevision"] == 2
        path.chmod(0o200)
        assert first.get(PATH, headers=new_headers).status_code == 503
        path.chmod(0o644)
        assert first.get(PATH, headers=new_headers).status_code == 503
        path.chmod(0o600)
        path.write_text('{"deploymentId":"a","deploymentId":"b"}')
        assert first.get(PATH, headers=new_headers).status_code == 503
        path.write_bytes(b" " * 16385)
        assert first.get(PATH, headers=new_headers).status_code == 503
    with TestClient(create_http_app(tmp_path / "none.sqlite", settings=settings(None))) as client:
        assert client.get(PATH, headers=HEADERS).status_code == 503
    assert load_settings(
        {"ZEBRA_RUNTIME_MANAGEMENT_CONFIG": str(path)}
    ).runtime_management_config == str(path)
    assert (
        replace(settings(None), runtime_management_config="relative.json").runtime_management_config
        == "relative.json"
    )


def test_timed_out_file_reads_keep_capacity_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx
    from fastapi import FastAPI
    from zebra_agent_api import runtime_management as module

    release = threading.Event()

    def blocked(*_args: object) -> dict[str, object]:
        release.wait(5)
        raise ValueError("late-private-path-must-not-escape")

    monkeypatch.setattr(module, "_config", blocked)
    app = FastAPI()
    module.register_runtime_management(app, settings(None), "local")

    async def check() -> None:
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://local.test"
            ) as client:
                responses = await asyncio.gather(
                    *(client.get(PATH, headers=HEADERS) for _ in range(8))
                )
                assert all(response.status_code == 503 for response in responses)
                assert (await client.get(PATH, headers=HEADERS)).status_code == 429
                assert all("private" not in response.text for response in responses)
        finally:
            release.set()
            await asyncio.sleep(0.05)

    asyncio.run(check())
