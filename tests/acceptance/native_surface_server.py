"""Owned local-compatibility native HTTP/PG fixture; no model or production IdP."""

import inspect
import json
import os
import secrets
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import UUID, uuid4

from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.tools import ToolCall
from agent_core.ports.platform_control_plane import AgentPlatformControlPlane
from agent_storage.postgres.client_capabilities import PostgresClientCapabilityRegistry
from agent_storage.postgres.client_effects import (
    PostgresClientEffectDispatch,
    PostgresClientEffectReceipts,
)
from agent_storage.postgres.client_sessions import (
    PostgresClientControlLeaseStore,
    PostgresClientSessionRegistry,
)
from agent_storage.postgres.events import PostgresEventStore
from agent_storage.postgres.migration_runner import apply_postgres_migrations
from zebra_agent_api.app import ZebraAgentApi
from zebra_agent_api.routes import RouteAdapter, RouteRequest
from zebra_agent_worker.client_tool_gateway import ClientGatewayContext, ClientToolGateway

from tests.api.test_client_runtime_api import _profile, _settings


def serve(folder: Path) -> None:
    repository = Path(__file__).resolve().parents[2]
    for component in (
        ZebraAgentApi,
        RouteAdapter,
        ClientToolGateway,
        PostgresClientSessionRegistry,
        PostgresClientEffectReceipts,
        PostgresClientCapabilityRegistry,
        _profile,
    ):
        assert Path(inspect.getfile(component)).resolve().is_relative_to(repository)
    cfg = json.loads((folder / "native-input.json").read_text())
    dsn = cfg["dsn"]
    namespace = "browser-" + uuid4().hex
    apply_postgres_migrations(dsn)
    profile = _profile()
    profiles = PostgresClientCapabilityRegistry(dsn, deployment_namespace=namespace)
    profiles.publish_profile(profile)
    sessions = PostgresClientSessionRegistry(dsn, deployment_namespace=namespace)
    leases = PostgresClientControlLeaseStore(dsn, deployment_namespace=namespace)
    dispatch = PostgresClientEffectDispatch(dsn, deployment_namespace=namespace)
    receipts = PostgresClientEffectReceipts(dsn, deployment_namespace=namespace)
    platform = AgentPlatformControlPlane(
        deployment_namespace=namespace,
        frontend_capabilities=profiles,
        client_sessions=sessions,
        client_control_leases=leases,
        client_effects=dispatch,
        client_effect_receipts=receipts,
    )
    db = str(folder / "native-local.sqlite")
    app = ZebraAgentApi(
        database_path=db, settings=replace(_settings(), database_url=db), client_platform=platform
    )
    adapter = RouteAdapter(app)
    task_id = TaskId(uuid4())
    parent_id = SessionId(uuid4())
    opened = adapter.handle(
        RouteRequest(
            "POST",
            "/v1/client-sessions",
            body={
                "grant": {
                    "grant_id": str(uuid4()),
                    "host_app_id": "fixture-host",
                    "namespace_id": "tenant-1",
                    "frontend_app_id": profile.frontend_app_id,
                    "origin": "https://app.fixture.example",
                    "user_ref": "fixture-user",
                    "profile_digest": profile.profile_digest,
                    "scopes": ["client.action"],
                    "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                }
            },
        )
    )
    assert opened.status_code == 201
    session_id = opened.body["client_session_id"]
    mount = {
        "client_session_id": session_id,
        "frontend_app_id": profile.frontend_app_id,
        "profile_revision": profile.revision,
        "profile_digest": profile.profile_digest,
        "mounted_actions": ["app.ui.item.open"],
        "mounted_readables": ["app.ui.route"],
        "ui_revision": 1,
        "mounted_at": datetime.now(UTC).isoformat(),
    }
    path = f"/v1/tasks/{task_id}/runs/run-1/client-surface"
    initial = adapter.handle(
        RouteRequest(
            "POST",
            path,
            headers={"X-Zebra-Client-Session": opened.body["session_credential"]},
            body={
                "mount": mount,
                "task_capability_scope": mount["mounted_actions"],
                "controller": True,
            },
        )
    )
    assert initial.status_code == 201, initial.body.get("reason")
    fixture_key = secrets.token_hex(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            self.handle_request()

        def do_POST(self):
            self.handle_request()

        def handle_request(self):
            size = int(self.headers.get("Content-Length", "0"))
            if size > 65536:
                return self.reply(413, {})
            body = json.loads(self.rfile.read(size)) if size else None
            if self.path.startswith("/fixture/"):
                if self.headers.get("X-Fixture-Key") != fixture_key:
                    return self.reply(401, {})
                if self.path == "/fixture/schedule":
                    client = UUID(session_id)
                    current = sessions.get_run_binding(task_id, "run-1", client)
                    lease = leases.get_active(current.binding_id)
                    gateway = ClientToolGateway(
                        context=ClientGatewayContext(
                            binding=current,
                            fence_hash=lease.fence_hash,
                            session_id=parent_id,
                            ui_revision=sessions.get_session(client).ui_revision,
                            action_contracts={action.name: action for action in profile.actions},
                        ),
                        dispatch=dispatch,
                    )
                    result = gateway.execute(
                        ToolCall(
                            tool_call_id=uuid4(),
                            created_at=datetime.now(UTC),
                            name="app.ui.item.open",
                            arguments={"itemId": body["itemId"]},
                        )
                    )
                    return self.reply(200, {"effectId": result.metadata["client_effect_id"]})
                if self.path == "/fixture/report":
                    # Recreate adapters to read durable state, not an in-memory acknowledgment.
                    stream = PostgresEventStore(
                        dsn, deployment_namespace=namespace
                    ).list_for_session(parent_id)
                    kinds = [event.event_type.value for event in stream]
                    return self.reply(
                        200,
                        {
                            "scheduled": kinds.count("client_effect_scheduled"),
                            "receipts": kinds.count("client_effect_receipt_accepted"),
                            "resumes": kinds.count("session_command_accepted"),
                        },
                    )
                return self.reply(404, {})
            response = adapter.handle(
                RouteRequest(self.command, self.path, headers=dict(self.headers), body=body)
            )
            self.reply(response.status_code, response.body)

        def reply(self, code, body):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    output = {
        "nativeUrl": f"http://127.0.0.1:{server.server_port}",
        "fixtureKey": fixture_key,
        "session": session_id,
        "credential": opened.body["session_credential"],
        "task": str(task_id),
        "path": path,
        "profile": {**profile.model_dump(mode="json"), "profile_digest": profile.profile_digest},
        "metadata": initial.body,
    }
    file = folder / "native-ready.json"
    fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(output, handle)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    serve(Path(sys.argv[1]))
