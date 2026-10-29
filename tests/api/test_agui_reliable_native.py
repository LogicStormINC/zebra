"""Actual signed Host grants, native profile binding and canonical-only reliable GET."""

import json
import os
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread
from time import monotonic, sleep
from uuid import uuid4

import httpx
import jwt
import uvicorn
from agent_core.domain.identifiers import TaskId
from agent_core.ports.task_projection_checkpoints import ProjectionScope
from agent_integrations.ag_ui.checkpoint_binding import build_projection_page_plan
from agent_integrations.ag_ui.checkpoint_materializer import AgUiCheckpointMaterializer
from agent_integrations.ag_ui.contracts import AgUiRunIdentity
from agent_integrations.ag_ui.profiles import AgUiProfileRegistry
from agent_integrations.ag_ui.standard_profiles import standard_profiles
from agent_security import PyJwtHostGrantDecoder
from agent_storage import HostRegistryRecord, PostgresHostAuthorityStore
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from zebra_agent_api.host_auth import PostgresHostGrantRequestAuthorizer
from zebra_agent_api.http import create_http_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest
from zebra_agent_api.stream_v2_authority import V2ReadAuthority
from zebra_agent_api.stream_v2_reader import StreamV2Reader

from tests.agent_integrations.binding_store_cases import resolve
from tests.agent_storage.test_postgres_projection_source_metadata import (
    metadata_dsn as _metadata_dsn,
)
from tests.api.test_agui_initial_native import initial_and_followup_native
from tests.api.test_postgres_host_auth_authorizer import _StaticResolver

metadata_dsn = _metadata_dsn


def materialize(stores, task, run_id, profiles):
    for method in (
        stores.tasks.backfill_event_positions,
        stores.tasks.backfill_replay_headers,
        stores.tasks.backfill_projection_sources,
    ):
        while not method(task, limit=256):
            pass
    run = stores.tasks.read_run_header(task, run_id)
    identity = AgUiRunIdentity(session_id=run.anchor.segment_id, thread_id=str(task), run_id=run_id)
    for profile in profiles:
        scope = ProjectionScope(
            stores.deployment_namespace, task, run.anchor.event_id, profile.checkpoint_version()
        )
        resolve(stores.tasks, run, scope)
        after = stores.tasks.read_checkpoint_head(scope).through_sequence
        while after < run.highwater:
            page = stores.tasks.read_event_page(
                task, after, limit=256, through_sequence=run.highwater
            )
            plan = build_projection_page_plan(
                stores.tasks, page, run, scope, identity, profile=profile
            )
            result = AgUiCheckpointMaterializer(stores.tasks, profile=profile).prepare_page(
                page, plan, scope, identity
            )
            stores.tasks.commit_projection_page(result)
            after = page.next_sequence


def test_signed_host_native_reliable_profile_does_not_require_transient_admission(
    metadata_dsn, tmp_path, monkeypatch
):
    answer = ("canonical reliable " * 1000).rstrip()
    app, context, verified, task, internal, native_headers, _, _, original, original_request = (
        initial_and_followup_native(metadata_dsn, tmp_path, monkeypatch, followup_answer=answer)
    )
    profiles = standard_profiles()
    materialize(app.stores, TaskId(task), internal, profiles)
    materialize(app.stores, TaskId(task), original_request.body["run"], profiles)
    namespace = app.stores.deployment_namespace
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    registry = PostgresHostAuthorityStore(metadata_dsn, deployment_namespace=namespace)
    registry.upsert_registry(
        HostRegistryRecord(
            host_app_id=context.host_app_id,
            namespace_id=context.namespace_id,
            issuer=verified.authority_issuer,
            audience="agui-gate",
            jwks_uri=verified.authority_issuer + "/jwks",
            allowed_origins=(context.origin,),
            algorithms=("RS256",),
            policy_version=context.policy_version,
        )
    )
    authorizer = PostgresHostGrantRequestAuthorizer(
        registry=registry, decoder=PyJwtHostGrantDecoder(_StaticResolver(private_key.public_key()))
    )
    reader = StreamV2Reader(
        V2ReadAuthority(app.stores, dsn=metadata_dsn, namespace=namespace),
        url=os.environ["ZEBRA_STREAM_TEST_REDIS_URL"],
        key=b"r" * 32,
        live_prefix="agui-native-" + uuid4().hex,
    )
    app = replace(app, agui_profiles=AgUiProfileRegistry(profiles), stream_v2_reader=reader)
    monkeypatch.setattr("zebra_agent_api.http.create_app", lambda *a, **k: app)

    def headers(profile=profiles[1].profile_id, **extra):
        now = int(datetime.now(UTC).timestamp())
        claims = {
            "iss": verified.authority_issuer,
            "aud": "agui-gate",
            "sub": verified.subject_ref,
            "jti": str(uuid4()),
            "iat": now - 1,
            "nbf": now - 1,
            "exp": now + 120,
            "host_app_id": context.host_app_id,
            "namespace_id": context.namespace_id,
            "workspace_ref": context.workspace_ref,
            "resource_refs": [
                {"type": ref.resource_type, "id": ref.resource_id} for ref in context.resource_refs
            ],
            "scopes": list(context.scopes),
            "limits": context.limits.model_dump(),
            "origin": context.origin,
            "policy_version": context.policy_version,
        }
        return {
            **native_headers,
            "X-Zebra-AGUI-Profile": profile,
            "Origin": context.origin,
            "Authorization": "Bearer " + jwt.encode(claims, private_key, algorithm="RS256"),
            **extra,
        }

    def forbidden(*a, **k):
        raise AssertionError("canonical profile queried transient draft metadata")

    monkeypatch.setattr("zebra_agent_api.stream_v2_reader.discover", forbidden)
    before = app.stores.events.list_for_session(task)
    assert before[-1].event_type.value == "turn_completed"
    path = f"/agui/threads/{task}/runs/{internal}"
    http = create_http_app(
        tmp_path / "unused-http.sqlite",
        settings=app.settings,
        stores=app.stores,
        host_grant_authorizer=authorizer,
    )
    config = uvicorn.Config(http, host="127.0.0.1", port=0, log_level="error", access_log=False)
    sock = config.bind_socket()
    origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
    server = uvicorn.Server(config)
    serving = Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    serving.start()
    deadline = monotonic() + 10
    while not server.started:
        assert monotonic() < deadline
        sleep(0.01)
    try:
        with httpx.Client(base_url=origin, timeout=10) as client:
            prepared = client.get(path + "/prepared", headers=headers())
            assert prepared.status_code == 200 and prepared.json()["status"] == "prepared", (
                prepared.text
            )
            response = client.get(path + "/stream", headers=headers())
            assert response.status_code == 200, response.text
            assert (
                '"type":"RUN_STARTED"' in response.text and '"type":"RUN_FINISHED"' in response.text
            )
            assert "zebra.canonical_chunk" in response.text
            assert "zebra.message_replace" not in response.text
            assert "zebra.stream.draft" not in response.text
            signed = [
                line[4:].strip() for line in response.text.splitlines() if line.startswith("id:")
            ]
            assert signed and all(token.startswith("v2p.") for token in signed)
            resumed = client.get(path + "/stream", headers=headers(**{"Last-Event-ID": signed[-1]}))
            assert resumed.status_code == 200 and "RUN_STARTED" not in resumed.text, resumed.text
            rejected = client.get(
                path + "/stream",
                headers=headers(profiles[0].profile_id, **{"Last-Event-ID": signed[-1]}),
            )
            assert rejected.status_code == 400
            invalid_client = headers(**{"X-Zebra-Client-Session": "invalid"})
            assert client.get(path + "/stream", headers=invalid_client).status_code == 401
            standard = client.get(
                path + "/prepared", headers=headers(profiles[0].profile_id)
            ).json()["input"]
            observed = client.post(
                path + "/stream", headers=headers(profiles[0].profile_id), json=standard
            )
            assert observed.status_code == 200 and observed.text.split("data: ")[1].startswith(
                '{"type":"RUN_STARTED"'
            ), observed.text
            # A second valid observer may consume public output, but cannot obtain
            # the original Client Session's private captured Readable input.
            grant = {
                **original_request.body["payload"]["surface"]["grant"],
                "grant_id": str(uuid4()),
            }
            opened = RouteAdapter(app).handle(
                RouteRequest(
                    "POST",
                    "/v1/client-sessions",
                    body={"grant": grant},
                    host_context=context,
                    verified_host_grant=verified,
                )
            )
            assert opened.status_code == 201, opened.body
            mount = {
                **original_request.body["payload"]["surface"]["mount"],
                "client_session_id": opened.body["client_session_id"],
                "ui_revision": 1,
                "mounted_at": datetime.now(UTC).isoformat(),
            }
            mounted = RouteAdapter(app).handle(
                RouteRequest(
                    "POST",
                    f"/v1/tasks/{task}/runs/{internal}/client-surface",
                    body={"mount": mount, "task_capability_scope": [], "controller": False},
                    headers={"X-Zebra-Client-Session": opened.body["session_credential"]},
                    host_context=context,
                    verified_host_grant=verified,
                )
            )
            assert mounted.status_code == 201, mounted.body
            observer = {"X-Zebra-Client-Session": opened.body["session_credential"]}
            hidden = client.get(path + "/prepared", headers=headers(**observer))
            assert hidden.status_code == 403 and "input" not in hidden.json(), hidden.text
            assert (
                client.post(
                    path + "/stream",
                    headers=headers(profiles[0].profile_id, **observer),
                    json=standard,
                ).status_code
                == 403
            )
            public = client.get(path + "/stream", headers=headers(**observer))
            assert public.status_code == 200 and "PRIVATE-READABLE-ONLY-A" not in public.text
            # The signed nonce is single-use even on read-only observation.
            nonce = headers()
            assert client.get(path + "/stream", headers=nonce).status_code == 200
            assert client.get(path + "/stream", headers=nonce).status_code == 403
        # The BFF is rebuilt for every receipt/read. The official consumer sees
        # actual first and follow-up public slices over authenticated native HTTP.
        meta = tmp_path / "native-http.json"
        meta.write_text(
            json.dumps(
                {
                    "origin": origin,
                    "taskId": str(task),
                    "headers": native_headers,
                    "privateKey": private_key.private_bytes(
                        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
                    ).decode(),
                    "context": context.model_dump(mode="json"),
                    "issuer": verified.authority_issuer,
                    "subject": verified.subject_ref,
                    "initial": {
                        "operation": original_request.path.rsplit("/", 1)[1],
                        "eventKey": original["command"]["idempotency_key"],
                        "run": original_request.body["run"],
                    },
                    "followup": {
                        "operation": native_headers["Idempotency-Key"],
                        "run": internal,
                        "answer": answer,
                    },
                }
            )
        )
        meta.chmod(0o600)
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [
                str(root / "sdks/typescript/node_modules/.bin/tsx"),
                str(root / "tests/conformance/agui_contract/native_http_gate.mts"),
                str(meta),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.should_exit = True
        serving.join(5)
        sock.close()
    assert app.stores.events.list_for_session(task) == before
