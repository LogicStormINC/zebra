"""Opt-in message anchoring never changes the legacy request or dispatches invalid input."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from zebra_agent_api.client_admission_operations import Admission


def request():
    return {
        "kind": "surface_mount",
        "task": str(uuid4()),
        "run": "run-new",
        "payload": {},
        "original_message": {
            "receipt_key": "original-message",
            "request_hash": "a" * 64,
            "event_id": str(uuid4()),
            "segment_id": str(uuid4()),
            "segment_sequence": 2,
        },
    }


def test_legacy_model_never_changes_its_default_digest_input():
    assert Admission(kind="surface_mount", task="task", run="run", payload={}).model_dump() == {
        "kind": "surface_mount",
        "task": "task",
        "run": "run",
        "payload": {},
    }
    with pytest.raises(ValueError):
        Admission.model_validate(request())


def test_explicit_message_request_keeps_reference():
    from zebra_agent_api.client_admission_message import MessageSurfaceAdmission

    raw = request()
    parsed = MessageSurfaceAdmission.model_validate(raw)
    assert parsed.model_dump() == raw


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "surface_open"},
        {"kind": "task_create"},
        {"task": "UPPERCASE"},
        {"original_message": {}},
        {"original_message": None},
    ],
)
def test_invalid_message_protocol_shape(change):
    from zebra_agent_api.client_admission_message import MessageSurfaceAdmission

    with pytest.raises(ValueError):
        MessageSurfaceAdmission.model_validate({**request(), **change})


@pytest.mark.parametrize(
    "key,value",
    [
        ("receipt_key", ""),
        ("receipt_key", "bad key"),
        ("request_hash", "bad"),
        ("event_id", "invalid"),
        ("segment_id", "invalid"),
        ("segment_sequence", True),
        ("segment_sequence", -1),
        ("segment_sequence", 9007199254740992),
        ("extra", True),
    ],
)
def test_invalid_reference_is_rejected(key, value):
    from zebra_agent_api.client_admission_message import MessageSurfaceAdmission

    raw = deepcopy(request())
    raw["original_message"][key] = value
    with pytest.raises(ValueError):
        MessageSurfaceAdmission.model_validate(raw)


def test_non_native_or_mixed_ports_fail_before_claim():
    from zebra_agent_api.client_admission_message import validate_message_surface

    raw = request()
    with pytest.raises(ValueError):
        validate_message_surface(SimpleNamespace(), raw)
