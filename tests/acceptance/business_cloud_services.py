"""Owned OIDC issuer, generic Broker and signed cloud Runtime composition; no model."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import ssl
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import jwt
import uvicorn
from cryptography.hazmat.primitives import serialization


def serve_idp(folder: Path, number: int) -> None:
    cfg = json.loads((folder / "fixture.json").read_text())
    key = serialization.load_pem_private_key((folder / "idp-signing.pem").read_bytes(), None)
    numbers = key.public_key().public_numbers()

    def b64(value: int) -> str:
        return (
            base64.urlsafe_b64encode(value.to_bytes((value.bit_length() + 7) // 8, "big"))
            .rstrip(b"=")
            .decode()
        )

    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "kid": "business-idp-key",
                "alg": "RS256",
                "use": "sig",
                "n": b64(numbers.n),
                "e": b64(numbers.e),
            }
        ]
    }
    codes: dict[str, dict[str, str]] = {}
    lock = threading.Lock()
    counts = {"exchanges": 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Never log codes, state, Cookie, Authorization or query parameters.

        def reply(self, status: int, body: object):
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            path = urllib.parse.urlsplit(self.path)
            if path.path == "/jwks":
                self.reply(200, jwks)
            elif path.path == "/stats":
                self.reply(200, counts)
            elif path.path == "/authorize":
                args = {k: v[0] for k, v in urllib.parse.parse_qs(path.query).items()}
                if (
                    args.get("client_id") != "business-bff"
                    or args.get("redirect_uri") != cfg["callback"]
                    or args.get("code_challenge_method") != "S256"
                    or not args.get("nonce")
                    or args.get("prompt") != "login"
                    or args.get("max_age") != "0"
                ):
                    self.reply(400, {})
                    return
                # Isolated IdP test account; never a browser supplied subject.
                code = secrets.token_urlsafe(32)
                with lock:
                    codes[code] = args
                self.send_response(302)
                self.send_header(
                    "Location",
                    cfg["callback"]
                    + "?"
                    + urllib.parse.urlencode({"state": args["state"], "code": code}),
                )
                self.end_headers()
            else:
                self.reply(404, {})

        def do_POST(self):
            if self.path != "/token":
                self.reply(404, {})
                return
            with lock:
                counts["exchanges"] += 1
            secret = json.loads((folder / "idp-secret.json").read_text())["secret"]
            expected = "Basic " + base64.b64encode(("business-bff:" + secret).encode()).decode()
            if self.headers.get("Authorization") != expected:
                self.reply(401, {})
                return
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 8192:
                self.reply(400, {})
                return
            body = {
                k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(size).decode()).items()
            }
            with lock:
                original = codes.pop(body.get("code", ""), None)
            challenge = (
                base64.urlsafe_b64encode(
                    hashlib.sha256(body.get("code_verifier", "").encode()).digest()
                )
                .rstrip(b"=")
                .decode()
            )
            if (
                original is None
                or original["code_challenge"] != challenge
                or body.get("redirect_uri") != cfg["callback"]
                or body.get("grant_type") != "authorization_code"
            ):
                self.reply(400, {})
                return
            now = int(time.time())
            claims = {
                "iss": cfg["idp"],
                "sub": "business-user",
                "aud": "business-bff",
                "iat": now,
                "exp": now + 180,
                "auth_time": now,
                "nonce": original["nonce"],
            }
            state = json.loads((folder / "business.json").read_text())
            if state.get("badNonce"):
                claims["nonce"] = "wrong-nonce"
            token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "business-idp-key"})
            if state.get("loseIdpResponse"):
                self.reply(503, {})
                return
            self.reply(
                200,
                {
                    "access_token": secrets.token_urlsafe(32),
                    "refresh_token": secrets.token_urlsafe(32),
                    "id_token": token,
                    "token_type": "Bearer",
                    "expires_in": 180,
                },
            )

    server = ThreadingHTTPServer(("127.0.0.1", number), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(folder / "tls.pem", folder / "tls.key")
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


def serve_cloud(folder: Path, mode: str, number: int) -> None:
    from agent_core.domain.cloud_scope import OpaqueAuthorityScope
    from agent_security import PyJwtHostGrantDecoder
    from agent_storage import PostgresHostAuthorityStore, postgres_control_plane_stores
    from zebra_agent_api import create_http_app
    from zebra_agent_api.host_auth import PostgresHostGrantRequestAuthorizer
    from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings
    from zebra_host_grant_broker.app import create_app
    from zebra_host_grant_broker.config import BrokerSettings

    cfg = json.loads((folder / "fixture.json").read_text())
    if mode == "broker":
        settings = BrokerSettings(
            issuer=cfg["broker"],
            audience="runtime-a",
            host_app_id="host-a",
            namespace_id="tenant-a",
            workspace_ref="unused",
            origin="https://ui.example",
            policy_version="host-v1",
            allowed_scopes=("agent.run",),
            private_key_pem=(folder / "signing.pem").read_text(),
            key_id="broker-key",
            ttl_seconds=8,
            trench_me_url="",
            trench_sources_url="",
            trench_timeout_seconds=1,
            max_runtime_seconds=60,
            max_model_tokens=1000,
            max_artifact_bytes=1048576,
            authority_mode="generic",
            authority_url=cfg["router"] + "/go1",
            authority_timeout_seconds=15,
        )
        app = create_app(settings)
    else:

        class LocalTLS:
            def resolve(self, uri, token, *, deadline=None):
                assert uri == cfg["broker"] + "/.well-known/jwks.json"
                budget = min(2, max(0.001, deadline - time.monotonic())) if deadline else 2
                with urllib.request.urlopen(
                    uri,
                    context=ssl.create_default_context(cafile=str(folder / "tls.pem")),
                    timeout=budget,
                ) as response:
                    raw = response.read(16385)
                    assert len(raw) <= 16384
                    return jwt.PyJWK.from_dict(json.loads(raw)["keys"][0]).key

        class NoObjects:
            def __getattr__(self, name):
                def denied(*args, **kwargs):
                    raise AssertionError("no artifact object I/O in cloud admission acceptance")

                return denied

        scope = OpaqueAuthorityScope(authority_issuer=cfg["broker"], namespace_id="tenant-a")
        stores = postgres_control_plane_stores(
            cfg["nativeDsn"],
            deployment_namespace="local",
            memory_cursor_signing_key=bytes.fromhex(cfg["baselineKey"]),
            artifact_objects=NoObjects(),
            history_scope=scope,
            continuation_scope=scope,
        )
        settings = ZebraAgentSettings(
            profile="cloud",
            database_url=cfg["nativeDsn"],
            development_unrestricted=True,
            client_integration_enabled=True,
            runtime_management_config=str(folder / "native-a.json"),
            host_management_config=str(folder / "native-h.json"),
            api=ApiSettings(auth_token="unused-fixture-only"),
            model=ModelSettings(
                provider="test",
                api_key_env="UNSET_CLOUD_MODEL",
                base_url="https://unused.example",
                model="unused",
            ),
        )
        authority = PostgresHostAuthorityStore(cfg["nativeDsn"], deployment_namespace="local")
        app = create_http_app(
            settings=settings,
            stores=stores,
            host_grant_origins=("https://ui.example",),
            host_grant_authorizer=PostgresHostGrantRequestAuthorizer(
                registry=authority, decoder=PyJwtHostGrantDecoder(LocalTLS())
            ),
        )
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=number,
        ssl_keyfile=str(folder / "tls.key"),
        ssl_certfile=str(folder / "tls.pem"),
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    target, selected, listen = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
    if selected == "idp":
        serve_idp(target, listen)
    else:
        serve_cloud(target, selected, listen)
