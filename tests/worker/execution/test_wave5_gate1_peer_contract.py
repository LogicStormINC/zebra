"""Frozen cross-repo contract fixture for the FinOS peer."""

import json
from pathlib import Path

from agent_core.contracts import validate_event_payload
from agent_core.domain.events import EventType


def test_wave5_gate1_peer_contract_fixture_validates() -> None:
    fixture_path = (
        Path(__file__).parents[2] / "fixtures" / "wave5_gate1_contract_delta_v1.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert fixture["schema_version"] == "zebra-wave5-gate1-contract-delta-v1"
    for item in fixture["events"]:
        event_type = EventType(item["event_type"])
        validate_event_payload(event_type, item["payload"])
    assert fixture["public_boundary"] == {
        "canonical_final": "accepted-attempt-only",
        "private_fields_excluded": [
            "messages_digest",
            "system_prompt_digest",
            "tool_schema_digest",
            "model_config_digest",
            "invocation_policy_digest",
            "resource_manifest_digest",
        ],
    }
