"""Public command admission uses actual mounts; SQLite proves durable Context recovery."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_core.domain.client_capabilities import ProfileLifecycle
from agent_storage import SQLiteEventStore
from zebra_agent_api.app import ZebraAgentApi
from zebra_agent_api.routes import RouteAdapter, RouteRequest
from zebra_agent_worker.task_recovery import recover_client_state_evidence

from tests.api.test_agui_command_routes import _seed_ready_session
from tests.api.test_client_runtime_api import _bundle, _profile, _settings


def setup_surface(tmp_path):
    db, task, revision = _seed_ready_session(tmp_path)
    platform = _bundle()
    profile = _profile()
    platform.frontend_capabilities.publish_profile(profile)
    app = ZebraAgentApi(
        database_path=db,
        settings=replace(_settings(), database_url=str(db)),
        client_platform=platform,
    )
    adapter = RouteAdapter(app)
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
    sid = opened.body["client_session_id"]
    headers = {
        "X-Zebra-Client-Session": opened.body["session_credential"],
        "Idempotency-Key": "state-1",
    }
    mount = {
        "client_session_id": sid,
        "frontend_app_id": profile.frontend_app_id,
        "profile_revision": 1,
        "profile_digest": profile.profile_digest,
        "ui_revision": 1,
        "mounted_actions": ["app.ui.item.open"],
        "mounted_readables": ["app.ui.route"],
        "mounted_at": datetime.now(UTC).isoformat(),
    }
    bound = adapter.handle(
        RouteRequest(
            "POST",
            f"/v1/tasks/{task}/runs/run-1/client-surface",
            headers=headers,
            body={
                "mount": mount,
                "task_capability_scope": ["app.ui.item.open"],
                "controller": False,
            },
        )
    )
    assert bound.status_code == 201
    # The in-memory registry fixture predates real stores' Session pointer update.
    platform.client_sessions.sessions[sid] = platform.client_sessions.sessions[sid].model_copy(
        update={"ui_revision": 1, "mounted_snapshot_digest": bound.body["mounted_snapshot_digest"]}
    )
    body = {
        "action": "run",
        "threadId": str(task),
        "runId": "run-1",
        "expectedRevision": revision,
        "input": {
            "state": {"app.ui.route": {"route": "/items", "authToken": "never-persist"}},
            "forwardedProps": {
                "clientStateVersion": 1,
                "frontendAppId": profile.frontend_app_id,
                "clientSessionId": sid,
                "uiRevision": 1,
                "profileDigest": profile.profile_digest,
                "mountedSnapshotDigest": bound.body["mounted_snapshot_digest"],
                "clientBindingDigest": bound.body["binding_digest"],
            },
        },
    }
    return adapter, platform, headers, body, db, task


def test_bound_readable_command_redacts_then_reopens_without_context_drift(tmp_path):
    adapter, _, headers, body, db, task = setup_surface(tmp_path)
    response = adapter.handle(RouteRequest("POST", "/agui/commands", headers=headers, body=body))
    assert response.status_code == 202, response.body
    stored = SQLiteEventStore(db).list_for_session(task)
    assert "never-persist" not in repr(stored)
    snapshot = stored[-1].payload["payload"]["client"]
    assert snapshot["client_state_admission_contract_version"] == 1
    assert snapshot["state_snapshot"]["app.ui.route"]["authToken"] == "__redacted__"
    from agent_context.adapter import LocalContextCompiler

    evidence = recover_client_state_evidence(SQLiteEventStore(db).list_for_session(task))
    prompt = LocalContextCompiler().build_system_prompt(
        task_input="Inspect page",
        workspace_root=tmp_path,
        max_tokens=2000,
        runtime_evidence=(evidence,),
    )
    assert "/items" in prompt and "never-persist" not in prompt
    replay = adapter.handle(RouteRequest("POST", "/agui/commands", headers=headers, body=body))
    assert replay.status_code in (200, 202)
    assert len(SQLiteEventStore(db).list_for_session(task)) == len(stored)


@pytest.mark.parametrize(
    "field,value",
    [
        ("clientStateVersion", 2),
        ("clientStateVersion", True),
        ("uiRevision", 0),
        ("uiRevision", True),
        ("clientSessionId", str(uuid4())),
        ("frontendAppId", "other-web"),
        ("profileDigest", "f" * 64),
        ("mountedSnapshotDigest", "f" * 64),
        ("clientBindingDigest", "f" * 64),
        ("authorization", "never-persist"),
    ],
)
def test_bound_metadata_drift_rejects_without_command_write(tmp_path, field, value):
    adapter, _, headers, body, db, task = setup_surface(tmp_path)
    body["input"]["forwardedProps"][field] = value
    before = SQLiteEventStore(db).list_for_session(task)
    response = adapter.handle(RouteRequest("POST", "/agui/commands", headers=headers, body=body))
    assert response.status_code in (400, 401, 403, 409, 422), response.body
    assert SQLiteEventStore(db).list_for_session(task) == before
    assert "never-persist" not in repr(response.body)


@pytest.mark.parametrize(
    "case",
    [
        "no-credential",
        "wrong-credential",
        "no-binding",
        "no-mount",
        "closed",
        "revoked",
        "unmounted-readable",
        "future-run",
    ],
)
def test_bound_current_session_profile_and_mount_fail_closed(tmp_path, case):
    adapter, platform, headers, body, db, task = setup_surface(tmp_path)
    sid = body["input"]["forwardedProps"]["clientSessionId"]
    if case == "no-credential":
        headers.pop("X-Zebra-Client-Session")
    if case == "wrong-credential":
        headers["X-Zebra-Client-Session"] = sid + ":" + ("x" * 32)
    if case == "no-binding":
        platform.client_sessions.bindings.clear()
    if case == "no-mount":
        platform.client_sessions.snapshots.clear()
    if case == "closed":
        platform.client_sessions.close_session(sid)
    if case == "revoked":
        profile = _profile().model_copy(update={"lifecycle": ProfileLifecycle.REVOKED})
        platform.frontend_capabilities.profiles[(profile.frontend_app_id, 1)] = profile
    if case == "unmounted-readable":
        body["input"]["state"]["app.ui.other"] = {"route": "/private"}
    if case == "future-run":
        body["runId"] = "other-run"
    before = SQLiteEventStore(db).list_for_session(task)
    response = adapter.handle(RouteRequest("POST", "/agui/commands", headers=headers, body=body))
    assert response.status_code in (400, 401, 403, 409, 422), response.body
    assert SQLiteEventStore(db).list_for_session(task) == before


def test_bound_state_dependency_failure_is_not_an_empty_success(tmp_path):
    adapter, platform, headers, body, db, task = setup_surface(tmp_path)

    def unavailable(*_):
        raise RuntimeError("never-persist")

    platform.client_sessions.get_mounted_snapshot = unavailable
    before = SQLiteEventStore(db).list_for_session(task)
    response = adapter.handle(RouteRequest("POST", "/agui/commands", headers=headers, body=body))
    assert response.status_code == 503 and "never-persist" not in repr(response.body)
    assert SQLiteEventStore(db).list_for_session(task) == before


@pytest.mark.parametrize(
    "state", [{"app.ui.route": {"x": float("nan")}}, {"app.ui.route": {"x": "a" * 66000}}]
)
def test_client_json_is_bounded_before_redaction(tmp_path, state):
    adapter, _, headers, body, db, task = setup_surface(tmp_path)
    body["input"]["state"] = state
    before = SQLiteEventStore(db).list_for_session(task)
    response = adapter.handle(RouteRequest("POST", "/agui/commands", headers=headers, body=body))
    assert response.status_code in (400, 422), response.body
    assert SQLiteEventStore(db).list_for_session(task) == before


def test_empty_snapshot_clears_recovery_and_missing_surface_never_falls_back(tmp_path):
    adapter, _, headers, body, db, task = setup_surface(tmp_path)
    body["input"]["state"] = {}
    accepted = adapter.handle(RouteRequest("POST", "/agui/commands", headers=headers, body=body))
    assert accepted.status_code == 202
    evidence = recover_client_state_evidence(SQLiteEventStore(db).list_for_session(task))
    assert evidence.metadata["state"] == {}
    from types import SimpleNamespace

    from zebra_agent_api.ag_ui_command import _admit_client_mounts

    command = {"input": {"state": {}, "forwardedProps": {"clientStateVersion": 1}}}
    app = SimpleNamespace(client_platform=None)
    denied = _admit_client_mounts(app, command, "/agui/commands")
    assert denied.status_code == 503


def test_cloud_mounted_state_requires_version_even_with_no_tools(tmp_path):
    from types import SimpleNamespace

    from zebra_agent_api.ag_ui_command import _admit_client_mounts

    adapter, platform, headers, body, _, _ = setup_surface(tmp_path)
    body["input"]["forwardedProps"].pop("clientStateVersion")
    app = SimpleNamespace(settings=SimpleNamespace(deployment="cloud"), client_platform=platform)
    denied = _admit_client_mounts(
        app,
        {"input": body["input"]},
        "/agui/commands",
        request=RouteRequest("POST", "/agui/commands", headers=headers),
    )
    assert denied.status_code == 400


def test_current_task_authority_is_checked_before_client_state_persists(tmp_path, monkeypatch):
    from zebra_agent_api.responses import ApiResponse

    adapter, _, headers, body, db, task = setup_surface(tmp_path)
    seen = []

    def denied(app, task_id, context, **scope):
        seen.append((task_id, scope["run_id"], scope["required_scope"]))
        return ApiResponse(403, {"status": "forbidden"})

    monkeypatch.setattr("zebra_agent_api.ag_ui_client_state.task_access_response", denied)
    before = SQLiteEventStore(db).list_for_session(task)
    response = adapter.handle(RouteRequest("POST", "/agui/commands", headers=headers, body=body))
    assert response.status_code == 403
    assert seen == [(str(task), "run-1", "agent.run")]
    assert SQLiteEventStore(db).list_for_session(task) == before


@pytest.mark.parametrize("shape", ["depth", "nodes"])
def test_raw_structural_budget_prevents_recursive_or_wide_state_work(tmp_path, shape):
    adapter, _, headers, body, db, task = setup_surface(tmp_path)
    if shape == "nodes":
        value = [0] * 4100
    else:
        value = {}
        for _ in range(35):
            value = {"x": value}
    body["input"]["state"] = {"app.ui.route": value}
    before = SQLiteEventStore(db).list_for_session(task)
    result = adapter.handle(RouteRequest("POST", "/agui/commands", headers=headers, body=body))
    assert result.status_code in (400, 422)
    assert SQLiteEventStore(db).list_for_session(task) == before


def test_new_numeric_snapshot_is_canonical_without_changing_schema_admission(tmp_path):
    adapter, _, headers, body, db, task = setup_surface(tmp_path)
    body["input"]["state"] = {"app.ui.route": {"negative": -0.0, "large": 1e100, "half": 0.5}}
    accepted = adapter.handle(RouteRequest("POST", "/agui/commands", headers=headers, body=body))
    assert accepted.status_code == 202
    evidence = recover_client_state_evidence(SQLiteEventStore(db).list_for_session(task))
    state = evidence.metadata["state"]["app.ui.route"]
    assert type(state["negative"]) is int and state["negative"] == 0
    assert type(state["large"]) is int and state["large"] == 10**100
    assert state["half"] == 0.5


def test_numeric_canonicalization_never_widens_schema_or_byte_budget():
    from agent_control_plane.agui_client_admission import (
        AgUiClientAdmissionError,
        admit_agui_client_payload,
    )
    from agent_core.domain.client_capabilities import ClientReadableContract

    profile = _profile().model_copy(
        update={
            "readables": (
                ClientReadableContract(name="app.ui.route", state_schema={"type": "integer"}),
            )
        }
    )
    with pytest.raises(AgUiClientAdmissionError, match="type integer"):
        admit_agui_client_payload(tools=[], state={"app.ui.route": 1.0}, profile=profile)
    profile = profile.model_copy(
        update={"readables": (ClientReadableContract(name="app.ui.route", max_state_bytes=16),)}
    )
    with pytest.raises(AgUiClientAdmissionError, match="byte budget"):
        admit_agui_client_payload(tools=[], state={"app.ui.route": 1e100}, profile=profile)
