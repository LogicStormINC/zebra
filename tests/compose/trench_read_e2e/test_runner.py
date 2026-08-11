from __future__ import annotations

import json
from pathlib import Path

from run_acceptance import MANIFEST, READ_TOOL_NAMES, REQUIRED_ENV, SCENARIOS
from support import ConfigError, decode_sse, load_config, missing_environment


def test_manifest_covers_each_acceptance_scenario_and_required_input() -> None:
    document = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert document["schema_version"] == "zebra.trench-read-e2e.runner-manifest.v1"
    assert {item["id"] for item in document["scenarios"]} == set(SCENARIOS)
    assert set(document["required_environment"]) == set(REQUIRED_ENV)
    script = Path(__file__).with_name("run_acceptance.py")
    assert script.is_file()


def test_missing_environment_is_explicit_and_never_a_skip() -> None:
    missing = missing_environment({}, REQUIRED_ENV)
    assert set(missing) == set(REQUIRED_ENV)
    try:
        load_config({}, REQUIRED_ENV)
    except ConfigError as error:
        assert error.missing == missing
        assert error.invalid == []
    else:
        raise AssertionError("empty environment must be blocked")


def test_sse_decoder_keeps_opaque_cursor_and_bounded_payload() -> None:
    event = decode_sse("cursor-1", ['{"type":"RUN_STARTED","runId":"run-1"}'])
    assert event is not None
    assert event.cursor == "cursor-1"
    assert event.data["type"] == "RUN_STARTED"
    assert decode_sse(None, []) is None


def test_read_tool_contract_is_exactly_the_five_trench_tools() -> None:
    assert READ_TOOL_NAMES == {
        "events.get_event",
        "events.get_evidence",
        "events.get_related_events",
        "events.get_entity_timeline",
        "events.get_topic",
    }
