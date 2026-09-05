"""Shared v1 broker envelope decoder contract; no broker or authority access."""

import copy
import importlib
import json
import traceback
from pathlib import Path

import pytest
from pydantic import ValidationError

MODULE = "agent_core.contracts.broker_envelope"
contract = importlib.import_module(MODULE)
ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
DOCS = ROOT / "docs/contracts"
BASE = {
    "message_id": "01234567-89ab-4cde-8123-0123456789ab",
    "message_type": "trench.ai.turn.ready",
    "schema_version": 1,
    "deployment_namespace": "dev",
    "scope": {"kind": "principal", "tenant_id": "tenant-1", "workspace_id": "workspace-1"},
    "aggregate_id": "turn-1",
    "operation_id": "turn-1",
    "wake_generation": 0,
    "idempotency_key": "turn-1:0",
    "correlation_id": "correlation-1",
    "causation_id": None,
    "occurred_at": "2026-09-04T10:00:00Z",
    "traceparent": None,
    "payload_ref": {"kind": "trench_turn", "id": "turn-1"},
}


def decode(value):
    return contract.parse_broker_envelope(json.dumps(value).encode())


def test_valid_and_frozen():
    envelope = decode(BASE)
    assert envelope.operation_id == "turn-1"
    with pytest.raises(ValidationError):
        envelope.operation_id = "changed"
    with pytest.raises(ValidationError):
        envelope.scope.tenant_id = "changed"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("schema_version", "1"),
        ("wake_generation", True),
        ("wake_generation", -1),
        ("wake_generation", 0.0),
        ("message_id", "bad"),
        ("message_id", "0123456789ab4cde81230123456789ab"),
        ("deployment_namespace", ""),
        ("deployment_namespace", " " * 2),
        ("deployment_namespace", "x" * 129),
        ("operation_id", "x" * 257),
        ("operation_id", None),
        ("operation_id", 1),
        ("correlation_id", "bad\nvalue"),
        ("causation_id", ""),
        ("causation_id", 4),
        ("occurred_at", "2026-09-04T10:00:00"),
        ("occurred_at", 1),
        ("occurred_at", "2026-02-30T10:00:00Z"),
        ("occurred_at", "2026-09-04 10:00:00Z"),
        ("traceparent", "00-" + "0" * 32 + "-" + "1" * 16 + "-01"),
        ("traceparent", "00-" + "1" * 32 + "-" + "0" * 16 + "-01"),
        ("traceparent", "01-" + "1" * 32 + "-" + "1" * 16 + "-01"),
        ("payload", {}),
        ("credential", "secret"),
        ("accepted_event_id", None),
        ("accepted_sequence", 1),
        ("aggregate_id", "other"),
        ("payload_ref", {"kind": "source_fetch_command", "id": "turn-1"}),
        ("payload_ref", {"kind": "trench_turn", "id": "other"}),
        ("payload_ref", {"kind": "trench_turn", "id": "turn-1", "url": "https://bad"}),
        ("scope", {"kind": "shared_source", "service_scope_id": "service-1"}),
        ("scope", {"kind": "principal", "tenant_id": "t", "workspace_id": "w", "extra": 1}),
    ],
)
def test_invalid_fields(key, value):
    with pytest.raises(ValueError):
        decode(BASE | {key: value})


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":1,"x":2}',
        b'{"x":{"y":1,"y":2}}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b"\xff",
        b"{}",
        b"null",
        b"[]",
        b"{} trailing",
        b" " * 16385,
        b"[" * 9 + b"0" + b"]" * 9,
        b"[" * 2000 + b"0" + b"]" * 2000,
    ],
)
def test_bad_bytes(raw):
    with pytest.raises(ValueError):
        contract.parse_broker_envelope(raw)


def test_byte_type():
    with pytest.raises(TypeError):
        contract.parse_broker_envelope("{}")


def test_no_trim_and_maximum_bytes():
    model = decode(BASE | {"deployment_namespace": " dev "})
    assert model.deployment_namespace == " dev "
    raw = json.dumps(BASE).encode()
    assert contract.parse_broker_envelope(raw + b" " * (16384 - len(raw)))
    with pytest.raises(ValueError):
        contract.parse_broker_envelope(raw + b" " * (16385 - len(raw)))


def test_zebra_evidence():
    value = copy.deepcopy(BASE)
    value.update(
        message_type="zebra.session.command.ready",
        aggregate_id="session-1",
        accepted_event_id=BASE["message_id"],
        accepted_sequence=1,
    )
    value["payload_ref"]["kind"] = "zebra_command"
    assert decode(value).accepted_sequence == 1
    for key, replacement in [
        ("accepted_sequence", True),
        ("accepted_sequence", 0),
        ("accepted_sequence", 1.0),
        ("accepted_event_id", "bad"),
        ("accepted_event_id", None),
    ]:
        with pytest.raises(ValueError):
            decode(value | {key: replacement})
    for key in ("accepted_sequence", "accepted_event_id"):
        missing = value.copy()
        del missing[key]
        with pytest.raises(ValueError):
            decode(missing)
    with pytest.raises(ValueError):
        decode(value | {"scope": {"kind": "shared_source", "service_scope_id": "shared"}})


def test_artifacts():
    examples = json.loads((DOCS / "broker-envelope-v1.examples.json").read_text())
    for example in examples["valid"]:
        decode(example)
    for example in examples["invalid"]:
        with pytest.raises(ValueError):
            decode(example)
    schema = json.loads((DOCS / "broker-envelope-v1.schema.json").read_text())
    assert schema == contract.broker_envelope_json_schema()
    sibling = ROOT.parent / ("Trench" if ROOT.name == "zebra-agent" else "zebra-agent")
    if (sibling / "docs/contracts/broker-envelope-v1.schema.json").exists():
        for filename in ("broker-envelope-v1.schema.json", "broker-envelope-v1.examples.json"):
            other = sibling / "docs/contracts" / filename
            assert (DOCS / filename).read_bytes() == other.read_bytes()


@pytest.mark.parametrize("key", list(BASE))
def test_required_fields(key):
    value = BASE.copy()
    del value[key]
    with pytest.raises(ValueError):
        decode(value)


@pytest.mark.parametrize("key", [k for k in BASE if k not in ("causation_id", "traceparent")])
def test_nonnullable_fields(key):
    with pytest.raises(ValueError):
        decode(BASE | {key: None})


def test_good_trace_and_offset():
    value = BASE | {
        "traceparent": "00-" + "1" * 32 + "-" + "2" * 16 + "-ff",
        "occurred_at": "2026-09-04T10:00:00.123456+08:00",
    }
    assert decode(value).traceparent == value["traceparent"]
    with pytest.raises(ValueError):
        decode(BASE | {"occurred_at": "2026-09-04T10:00:00+08:60"})


def test_decoder_depth_and_overflow():
    contract._check_depth([[[[[[[[]]]]]]]])
    with pytest.raises(ValueError, match="maximum depth"):
        contract._check_depth([[[[[[[[[]]]]]]]]])
    with pytest.raises(ValueError, match="nonfinite"):
        contract.parse_broker_envelope(b'{"x":1e999}')


@pytest.mark.parametrize("field", ["Cookie", "token", "message_type", "operation_id"])
def test_error_does_not_expose_credentials(field):
    sentinel = "SENTINEL-CREDENTIAL-DO-NOT-LOG"
    value = BASE | {field: sentinel}
    try:
        decode(value)
    except ValueError as error:
        assert sentinel not in str(error)
        assert sentinel not in traceback.format_exc()
    else:
        pytest.fail("untrusted envelope should be rejected")
