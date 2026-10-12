from uuid import uuid4

import pytest
from agent_core.contracts.session_commands import (
    SessionCommand,
    SessionCommandKind,
    validate_accepted_session_command,
)
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.stream_admission import RunStreamAdmission, StreamCapabilities, StreamMode


def capabilities():
    return StreamCapabilities(
        wire_version=2,
        provisional_draft_label=True,
        replace_message=True,
        reset_provisional=True,
        scoped_resume=True,
    )


def command():
    task = TaskId(uuid4())
    return SessionCommand(
        session_id=SessionId(uuid4()),
        kind=SessionCommandKind.RUN,
        expected_revision=3,
        idempotency_key="intent",
        payload={
            "thread_id": str(task),
            "run_id": "run-1",
            "stream_capabilities": capabilities().model_dump(),
        },
    )


def test_server_metadata_does_not_change_intent_and_is_integrity_bound():
    value = command()
    admission = RunStreamAdmission(
        task_id=TaskId(value.payload["thread_id"]),
        run_id="run-1",
        capabilities=capabilities(),
        mode=StreamMode.TRANSIENT_V2,
    )
    legacy = value.event_payload(
        stream_admission=admission.model_copy(update={"mode": StreamMode.LEGACY})
    )
    transient = value.event_payload(stream_admission=admission)
    assert transient["fingerprint"] == legacy["fingerprint"] == value.fingerprint
    assert (
        validate_accepted_session_command(
            transient, session_id=value.session_id, idempotency_key="intent"
        ).stream_admission
        == admission
    )
    transient["stream_admission"]["run_id"] = "other"
    with pytest.raises(ValueError, match="stream admission"):
        validate_accepted_session_command(
            transient, session_id=value.session_id, idempotency_key="intent"
        )


def test_capabilities_are_fingerprinted_and_server_mode_cannot_be_spoofed():
    value = command()
    changed = value.model_copy(update={"payload": {**value.payload, "stream_capabilities": {}}})
    assert changed.fingerprint != value.fingerprint
    with pytest.raises(ValueError, match="server-owned"):
        SessionCommand(
            **{**value.model_dump(), "payload": {"stream_admission": {"mode": "transient_v2"}}}
        )
