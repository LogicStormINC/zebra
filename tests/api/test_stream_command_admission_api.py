from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agent_core.domain.stream_admission import TransientCapacityPolicy
from agent_storage import sqlite_control_plane_stores
from zebra_agent_api.ag_ui_command import AgUiCommandEnvelope, _command_payload
from zebra_agent_api.command_submission import submit_session_command

from tests.agent_core.test_stream_command_admission import capabilities
from tests.api.test_session_command_routes import _seed_ready_session
from tests.worker.test_task_binding_host_context import _context, _verified


def test_idempotent_admission_survives_flag_change_and_new_intent_conflicts(tmp_path):
    path, session, revision = _seed_ready_session(tmp_path)
    stores = sqlite_control_plane_stores(path)
    tasks = Mock()
    tasks.read_task_header.return_value = SimpleNamespace(
        active_segment_id=session, strict_coverage=False
    )
    proxy = SimpleNamespace(events=stores.events, sessions=stores.sessions, tasks=tasks)
    body = {
        "kind": "run",
        "expected_revision": revision,
        "payload": {
            "thread_id": str(session),
            "run_id": "run-1",
            "stream_capabilities": capabilities().model_dump(),
        },
    }
    first = submit_session_command(
        proxy,
        str(session),
        body,
        idempotency_key="v2",
        transient_admission_enabled=True,
        capacity_policy=TransientCapacityPolicy(),
        verified_host_grant=_verified(_context()),
    )
    assert first.status_code == 202 and first.body["stream_admission"]["mode"] == "transient_v2"
    assert first.body["stream_admission"]["capacity_digest"] == TransientCapacityPolicy().digest
    tasks.read_task_header.side_effect = RuntimeError("must not renegotiate on retry")
    duplicate = submit_session_command(
        proxy, str(session), body, idempotency_key="v2", transient_admission_enabled=False,
        capacity_policy=TransientCapacityPolicy(epoch="future", run_slots=1),
    )
    assert (
        duplicate.status_code == 200
        and duplicate.body["stream_admission"] == first.body["stream_admission"]
    )
    changed = {**body, "payload": {**body["payload"], "stream_capabilities": {}}}
    assert (
        submit_session_command(proxy, str(session), changed, idempotency_key="v2").status_code
        == 409
    )
    assert tasks.read_task_header.call_count == 1


@pytest.mark.parametrize("coverage,mode", [(False, "transient_v2"), (True, "legacy")])
def test_source_coverage_cannot_select_temporary_drafts(tmp_path, coverage, mode):
    path, session, revision = _seed_ready_session(tmp_path)
    stores = sqlite_control_plane_stores(path)
    tasks = Mock()
    tasks.read_task_header.return_value = SimpleNamespace(
        active_segment_id=session, strict_coverage=coverage
    )
    response = submit_session_command(
        SimpleNamespace(events=stores.events, sessions=stores.sessions, tasks=tasks),
        str(session),
        {
            "kind": "run",
            "expected_revision": revision,
            "payload": {
                "thread_id": str(session),
                "run_id": "run-1",
                "stream_capabilities": capabilities().model_dump(),
            },
        },
        idempotency_key="source",
        transient_admission_enabled=True,
        verified_host_grant=_verified(_context()),
    )
    if mode == "legacy":
        assert "stream_admission" not in response.body
    else:
        assert response.body["stream_admission"]["mode"] == mode


def test_raw_metadata_spoofing_and_agui_capabilities(tmp_path):
    path, session, revision = _seed_ready_session(tmp_path)
    stores = sqlite_control_plane_stores(path)
    for body in (
        {"kind": "run", "expected_revision": revision, "stream_admission": {}},
        {"kind": "run", "expected_revision": revision, "payload": {"stream_admission": {}}},
    ):
        assert (
            submit_session_command(stores, str(session), body, idempotency_key="spoof").status_code
            == 400
        )
    envelope = AgUiCommandEnvelope.model_validate(
        {
            "action": "run",
            "threadId": str(session),
            "runId": "run-1",
            "expectedRevision": revision,
            "streamCapabilities": capabilities().model_dump(),
        }
    )
    assert _command_payload(envelope)["stream_capabilities"] == capabilities().model_dump()


def test_internal_unsigned_command_stays_legacy_and_unknown_source_rejects(tmp_path):
    path, session, revision = _seed_ready_session(tmp_path)
    stores = sqlite_control_plane_stores(path)
    body = {
        "kind": "run",
        "expected_revision": revision,
        "payload": {
            "thread_id": str(session),
            "run_id": "run-1",
            "stream_capabilities": capabilities().model_dump(),
        },
    }
    response = submit_session_command(
        stores, str(session), body, idempotency_key="unsigned", transient_admission_enabled=True
    )
    assert response.status_code == 202 and "stream_admission" not in response.body
    path, session, revision = _seed_ready_session(tmp_path / "other")
    stores = sqlite_control_plane_stores(path)
    tasks = Mock()
    tasks.read_task_header.side_effect = TimeoutError()
    body["expected_revision"] = revision
    body["payload"]["thread_id"] = str(session)
    response = submit_session_command(
        SimpleNamespace(events=stores.events, sessions=stores.sessions, tasks=tasks),
        str(session),
        body,
        idempotency_key="unknown",
        transient_admission_enabled=True,
        verified_host_grant=_verified(_context()),
    )
    assert response.status_code == 503


@pytest.mark.parametrize("reason", ["flag_off", "unsigned", "coverage", "capability_free"])
def test_new_capable_client_legacy_acceptance_remains_old_worker_compatible(tmp_path, reason):
    import hashlib
    import json

    from agent_core.contracts.session_commands import SessionCommandKind
    from pydantic import BaseModel, ConfigDict

    class OldAcceptedCommand(BaseModel):
        model_config = ConfigDict(extra="forbid")
        command_id: str
        session_id: str
        kind: SessionCommandKind
        expected_revision: int
        idempotency_key: str
        payload: dict[str, object]
        fingerprint: str
        extension_snapshot_digest: str | None = None
        extension_turn_id: str | None = None

    path, session, revision = _seed_ready_session(tmp_path)
    stores = sqlite_control_plane_stores(path)
    tasks = Mock()
    tasks.read_task_header.return_value = SimpleNamespace(
        active_segment_id=session, strict_coverage=reason == "coverage"
    )
    proxy = SimpleNamespace(events=stores.events, sessions=stores.sessions, tasks=tasks)
    body = {
        "kind": "run",
        "expected_revision": revision,
        "payload": {
            "thread_id": str(session),
            "run_id": "run-1",
            "stream_capabilities": capabilities().model_dump(),
        },
    }
    if reason == "capability_free":
        body["payload"].pop("stream_capabilities")
    first = submit_session_command(
        proxy,
        str(session),
        body,
        idempotency_key="legacy-caps",
        transient_admission_enabled=reason != "flag_off",
        verified_host_grant=None if reason == "unsigned" else _verified(_context()),
    )
    assert first.status_code == 202 and "stream_admission" not in first.body
    event = stores.events.list_for_session(session)[-1]
    old = OldAcceptedCommand.model_validate(event.payload)
    intent = {
        "session_id": old.session_id,
        "kind": old.kind.value,
        "expected_revision": old.expected_revision,
        "payload": old.payload,
    }
    assert (
        old.fingerprint
        == hashlib.sha256(
            json.dumps(intent, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    tasks.read_task_header.side_effect = AssertionError("retry must not renegotiate frozen legacy")
    retry = submit_session_command(
        proxy,
        str(session),
        body,
        idempotency_key="legacy-caps",
        transient_admission_enabled=True,
        verified_host_grant=_verified(_context()),
    )
    assert retry.status_code == 200 and "stream_admission" not in retry.body
    assert retry.body["event_sequence"] == first.body["event_sequence"]
