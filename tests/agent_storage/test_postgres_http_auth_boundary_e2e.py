"""Real HTTP/auth-boundary E2E over cloud PostgreSQL (gate 2).

Boots the ACTUAL FastAPI app on a real uvicorn socket and drives it
with a real HTTP client. The cloud auth boundary is exercised for
real: RS256-signed Host Grants verified against a PostgreSQL authority
registry (only the JWKS key resolver is a static test seam — signature,
scope, origin, expiry and replay-jti checks are production code). The
session created through the verified grant then completes through the
default Worker loop.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
import uvicorn
from agent_storage import HostRegistryRecord, PostgresHostAuthorityStore
from agent_storage.runtime_composition import CloudCompositionSettings
from cryptography.hazmat.primitives.asymmetric import rsa
from zebra_agent_api.host_auth import (
    PostgresHostGrantRequestAuthorizer,
    PyJwtHostGrantDecoder,
)
from zebra_agent_api.http import create_http_app

from tests.agent_storage.test_postgres_default_chain_e2e import (
    PARENT_PROMPT,
    _settings,
)

ISSUER = "https://api.trench-e2e.example.com"
ORIGIN = "https://trench-e2e.example.com"
AUDIENCE = "zebra-embedded"


class _StaticResolver:
    """Test-only JWKS seam: the RS256 signature check stays real."""

    def __init__(self, key: object) -> None:
        self._key = key

    def resolve(self, jwks_uri: str, token: str) -> object:
        assert jwks_uri.startswith("https://")
        return self._key


def _registry(tenant: str) -> HostRegistryRecord:
    return HostRegistryRecord(
        host_app_id="trench-e2e",
        namespace_id=tenant,
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_uri=f"{ISSUER}/.well-known/jwks.json",
        allowed_origins=(ORIGIN,),
        algorithms=("RS256",),
        policy_version="policy-v1",
    )


def _claims(jti: str, tenant: str, *, scopes: list[str] | None = None) -> dict:
    now = int(datetime.now(UTC).timestamp())
    return {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "opaque-subject",
        "jti": jti,
        "iat": now - 1,
        "nbf": now - 1,
        "exp": now + 600,
        "host_app_id": "trench-e2e",
        "namespace_id": tenant,
        "workspace_ref": "workspace-e2e",
        "resource_refs": [{"type": "trench.event", "id": "evt-e2e"}],
        "scopes": scopes if scopes is not None else ["agent.run"],
        "limits": {
            "max_runtime_seconds": 300,
            "max_model_tokens": 100_000,
            "max_artifact_bytes": 10_485_760,
        },
        "origin": ORIGIN,
        "policy_version": "policy-v1",
    }


@pytest.fixture
def boundary(
    postgres_dsn: str,
    cloud_composition: CloudCompositionSettings,
    namespace: str,
    stub_model_server: str,
    tmp_path: Path,
):
    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2048)
    registry = PostgresHostAuthorityStore(postgres_dsn, deployment_namespace=namespace)
    registry.upsert_registry(_registry(namespace))
    authorizer = PostgresHostGrantRequestAuthorizer(
        registry=registry,
        decoder=PyJwtHostGrantDecoder(_StaticResolver(private_key.public_key())),
    )
    cloud = CloudCompositionSettings(
        dsn=postgres_dsn,
        deployment_namespace=namespace,
        memory_cursor_signing_key=cloud_composition.memory_cursor_signing_key,
        artifact_objects=cloud_composition.artifact_objects,
        history_scope=cloud_composition.history_scope,
        continuation_scope=cloud_composition.continuation_scope,
    )
    http_app = create_http_app(
        tmp_path / "unused.sqlite",
        settings=_settings(stub_model_server, postgres_dsn),
        cloud_composition=cloud,
        host_grant_authorizer=authorizer,
    )
    api = getattr(http_app.state, "zebra_api", None)
    if api is None:
        # create_http_app composes the application object internally.
        from zebra_agent_api.factory import create_app

        api = create_app(
            tmp_path / "unused.sqlite",
            settings=_settings(stub_model_server, postgres_dsn),
            cloud_composition=cloud,
        )
    server = uvicorn.Server(
        uvicorn.Config(http_app, host="127.0.0.1", port=0, log_level="critical")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "uvicorn failed to start"
    port = server.servers[0].sockets[0].getsockname()[1]
    yield {
        "base_url": f"http://127.0.0.1:{port}",
        "sign": lambda claims: jwt.encode(claims, private_key, algorithm="RS256"),
        "api": api,
        "cloud": cloud,
    }
    server.should_exit = True
    thread.join(timeout=10)


def test_http_auth_boundary_full_chain(
    postgres_dsn: str,
    namespace: str,
    boundary,
    stub_model_server: str,
    tmp_path: Path,
) -> None:
    base_url = boundary["base_url"]
    sign = boundary["sign"]
    grant = sign(_claims(f"jti-{uuid4()}", namespace))
    payload = {
        "title": "http-boundary-e2e",
        "prompt": PARENT_PROMPT,
        "workspace": str(tmp_path),
        "execute": True,
    }

    with httpx.Client(base_url=base_url, timeout=30) as client:
        assert client.get("/health").status_code == 200

        anonymous = client.post("/sessions", json=payload)
        assert anonymous.status_code == 401
        assert anonymous.json()["reason"] == "missing_or_invalid_host_grant"

        garbage = client.post(
            "/sessions",
            json=payload,
            headers={"Authorization": "Bearer not-a-grant", "Origin": ORIGIN},
        )
        assert garbage.status_code == 403
        assert garbage.json()["reason"] == "host_grant_rejected"

        bad_origin = client.post(
            "/sessions",
            json=payload,
            headers={
                "Authorization": f"Bearer {grant}",
                "Origin": "https://evil.example.com",
            },
        )
        assert bad_origin.status_code == 403
        assert bad_origin.json()["reason"] == "host_origin_not_allowed"

        wrong_scope = sign(
            _claims(f"jti-{uuid4()}", namespace, scopes=["trench.event.read"])
        )
        missing_scope = client.post(
            "/sessions",
            json=payload,
            headers={"Authorization": f"Bearer {wrong_scope}", "Origin": ORIGIN},
        )
        assert missing_scope.status_code == 403

        # Grants are single-use (jti consumed per request), so each HTTP
        # call carries a fresh one — replay semantics live at the
        # Idempotency-Key layer, not by reusing the bearer.
        def fresh_headers() -> dict[str, str]:
            return {
                "Authorization": f"Bearer {sign(_claims(f'jti-{uuid4()}', namespace))}",
                "Origin": ORIGIN,
            }

        key = f"http-e2e-{uuid4()}"
        consumed = fresh_headers()
        first = client.post(
            "/sessions",
            json=payload,
            headers={**consumed, "Idempotency-Key": key},
        )
        assert first.status_code == 201, first.text
        body = first.json()
        assert body.get("command") is not None
        session_id = body["session_id"]

        replay = client.post(
            "/sessions",
            json=payload,
            headers={**fresh_headers(), "Idempotency-Key": key},
        )
        assert replay.status_code == 201
        assert replay.json() == body, "HTTP replay must return the identical body"

        conflict = client.post(
            "/sessions",
            json={**payload, "prompt": "different"},
            headers={**fresh_headers(), "Idempotency-Key": key},
        )
        assert conflict.status_code == 409
        assert conflict.json()["status"] == "idempotency_conflict"

        reused = client.post(
            "/sessions",
            json={**payload, "title": "reused-grant"},
            headers=consumed,
        )
        assert reused.status_code == 403, "consumed jti must not authorize again"

    # The HTTP-created session completes through the DEFAULT Worker loop.
    from zebra_agent_worker.loop import build_worker_loop_service

    loop = build_worker_loop_service(
        database_path=tmp_path / "unused.sqlite",
        settings=_settings(stub_model_server, postgres_dsn),
        cloud_composition=boundary["cloud"],
    )
    from agent_core.domain.identifiers import SessionId

    app = boundary["api"]
    for _ in range(160):
        loop.poll_once(worker_id="http-e2e-worker")
        session = app.stores.sessions.get_session(SessionId(UUID(session_id)))
        if session is not None and session.status.value == "completed":
            break
    session = app.stores.sessions.get_session(SessionId(UUID(session_id)))
    assert session is not None
    assert session.status.value == "completed", (
        "the HTTP-created session must complete through the default worker"
    )
    events = app.stores.events.list_for_session(SessionId(UUID(session_id)))
    from agent_core.domain.events import EventType

    assert any(
        event.event_type is EventType.EXECUTION_AUTHORITY_RESOLVED for event in events
    ), "the verified grant must back the session's frozen binding authority"
