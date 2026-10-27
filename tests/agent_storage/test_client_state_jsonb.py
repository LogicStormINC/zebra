"""Read-only JSONB transport of a newly admitted snapshot; no tables or migrations."""

import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from agent_control_plane.agui_client_admission import admit_agui_client_payload
from agent_core.contracts import SessionCommand, SessionCommandKind
from agent_core.domain.client_capabilities import (
    ClientReadableContract,
    FrontendCapabilityProfileVersion,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from zebra_agent_worker.task_recovery import recover_client_state_evidence


def test_admitted_state_digest_survives_actual_postgres_jsonb():
    dsn = os.environ.get("ZEBRA_TEST_CLIENT_STATE_PG_DSN")
    if not dsn:
        pytest.skip("dedicated owned JSONB test DSN not configured")
    profile = FrontendCapabilityProfileVersion(
        frontend_app_id="fixture-web",
        revision=1,
        readables=(ClientReadableContract(name="app.ui.route"),),
    )
    admitted = admit_agui_client_payload(
        tools=[],
        profile=profile,
        state={
            "app.ui.route": {
                "negative": -0.0,
                "integer": 1.0,
                "large": 1e100,
                "small": 1e-100,
                "nested": [-1e100, 1.23e80, 0.125],
                "label": "页面 😀 e\u0301",
                "authToken": "never-persist",
            }
        },
    )
    command = SessionCommand(
        session_id=new_session_id(),
        kind=SessionCommandKind.RUN,
        expected_revision=0,
        idempotency_key=str(uuid4()),
        payload={
            "client": {
                "client_session_id": str(uuid4()),
                "frontend_app_id": profile.frontend_app_id,
                "profile_digest": profile.profile_digest,
                "ui_revision": 1,
                "state_snapshot": admitted.sanitized_state,
                "state_digest": admitted.state_digest,
                "redacted_keys": list(admitted.redacted_keys),
            }
        },
    )
    from psycopg.types.json import Jsonb

    before = command.event_payload()
    with psycopg.connect(dsn, connect_timeout=5, options="-c statement_timeout=5000") as connection:
        for invalid in [{"value": "\x00"}, {"value": "\ud800"}, {"\x00": "value"}]:
            with pytest.raises(psycopg.Error), connection.transaction():
                connection.execute("SELECT %s::jsonb", (Jsonb(invalid),)).fetchone()
        restored = connection.execute("SELECT %s::jsonb", (Jsonb(before),)).fetchone()[0]
    assert json.dumps(before, sort_keys=True) == json.dumps(restored, sort_keys=True)
    event = SessionEvent.create(
        session_id=command.session_id,
        sequence=0,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=restored,
        created_at=datetime.now(UTC),
    )
    evidence = recover_client_state_evidence([event])
    assert evidence.metadata["state_digest"] == admitted.state_digest
    assert evidence.metadata["state"] == admitted.sanitized_state
    assert "never-persist" not in repr(restored)


@pytest.mark.parametrize(
    "state",
    [
        {"app.ui.route": {"x": "\x00"}},
        {"app.ui.route": {"x": "\ud800"}},
        {"app.ui.route": {"\x00": "x"}},
    ],
)
def test_new_state_rejects_nonportable_jsonb_text_before_storage(state):
    from agent_control_plane.agui_client_admission import AgUiClientAdmissionError

    with pytest.raises(AgUiClientAdmissionError, match="NUL|UTF-8"):
        admit_agui_client_payload(tools=[], profile=None, state=state)
