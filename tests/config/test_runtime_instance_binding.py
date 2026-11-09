import base64
from dataclasses import replace

from zebra_agent_config import load_settings
from zebra_agent_config.bundle_settings import baseline_digest
from zebra_agent_config.runtime_instance_binding import load_runtime_instance_id

INSTANCE = "a0000000-0000-4000-8000-000000000001"


def test_runtime_instance_is_opt_in_and_not_a_bundle_baseline_input() -> None:
    original = load_settings({})
    bound = replace(
        original, runtime_instance_id=INSTANCE, runtime_gate_config="/private/gate.json"
    )
    assert baseline_digest(original, "a" * 64) == baseline_digest(bound, "a" * 64)
    assert load_runtime_instance_id({}) is None
    values = {
        "ZEBRA_RUNTIME_INSTANCE_ID": INSTANCE,
        "ZEBRA_RUNTIME_GATE_CONFIG": "/private/gate.json",
        "ZEBRA_RUNTIME_INSTANCE_BINDING_KEY": "rtbind_"
        + base64.urlsafe_b64encode(b"a" * 32).decode().rstrip("="),
    }
    assert load_runtime_instance_id(values) == INSTANCE
    assert "rtbind_" not in repr(bound)


def test_runtime_instance_rejects_invalid_identity_or_key_without_leaking_it() -> None:
    for values in (
        {"ZEBRA_RUNTIME_INSTANCE_ID": INSTANCE},
        {"ZEBRA_RUNTIME_INSTANCE_ID": "not-an-id", "ZEBRA_RUNTIME_GATE_CONFIG": "/gate"},
        {
            "ZEBRA_RUNTIME_INSTANCE_ID": INSTANCE,
            "ZEBRA_RUNTIME_GATE_CONFIG": "/gate",
            "ZEBRA_RUNTIME_INSTANCE_BINDING_KEY": "private-invalid-value",
        },
    ):
        try:
            load_runtime_instance_id(values)
        except ValueError as error:
            assert "private-invalid-value" not in str(error)
        else:
            raise AssertionError("untrusted process binding accepted")
