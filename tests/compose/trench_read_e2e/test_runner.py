from __future__ import annotations

import json
from pathlib import Path

from run_acceptance import (
    MANIFEST,
    READ_TOOL_NAMES,
    REQUIRED_ENV,
    SCENARIOS,
    append_task_message,
    control_command,
    run_command,
    wait_task_terminal,
    worker_restart,
)
from support import ConfigError, decode_sse, load_config, missing_environment, task_state


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


def test_database_and_redis_dsns_are_not_validated_as_http_endpoints() -> None:
    environment = {name: "https://service.local" for name in REQUIRED_ENV}
    environment.update(
        {
            "TRENCH_E2E_SESSION_COOKIE": "trench_ai_session=fixture",
            "TRENCH_E2E_EVENT_ID": "event-1",
            "TRENCH_E2E_DATABASE_DSN": "postgresql://localhost/trench",
            "TRENCH_E2E_REDIS_URL": "redis://localhost:6379/0",
            "ZEBRA_E2E_DATABASE_DSN": "postgresql://localhost/zebra",
            "ZEBRA_E2E_REDIS_URL": "redis://localhost:6379/1",
        }
    )

    config = load_config(environment, REQUIRED_ENV)

    assert config.trench_redis_url == "redis://localhost:6379/0"
    assert config.zebra_redis_url == "redis://localhost:6379/1"


def test_sse_decoder_keeps_opaque_cursor_and_bounded_payload() -> None:
    event = decode_sse("cursor-1", ['{"type":"RUN_STARTED","runId":"run-1"}'])
    assert event is not None
    assert event.cursor == "cursor-1"
    assert event.data["type"] == "RUN_STARTED"
    assert decode_sse(None, []) is None


def test_read_tool_contract_includes_trench_native_history_tools() -> None:
    assert READ_TOOL_NAMES == {
        "events.get_event",
        "events.get_evidence",
        "events.get_related_events",
        "events.get_entity_timeline",
        "events.get_topic",
        "sources.list",
        "sources.get_status",
        "subscriptions.list_history",
        "events.search_history",
        "events.get_historical_event",
        "events.trace_historical_event",
        "sources.add",
        "sources.inspect_url",
        "sources.pause",
        "sources.remove",
        "sources.resolve_candidate",
        "sources.resume",
        "sources.search",
    }


def test_worker_restart_uses_declared_operator_header(monkeypatch) -> None:
    captured = {}

    class Response:
        status = 200

    monkeypatch.setattr(
        "run_acceptance.request",
        lambda method, url, **kwargs: captured.update(kwargs) or Response(),
    )
    config = type(
        "Config",
        (),
        {
            "operator_token": "operator-token",
            "request_id": "request-id",
            "worker_restart_url": "https://operator.local/worker-restart",
            "timeout_seconds": 30,
        },
    )()

    worker_restart(config, "task", "run")

    assert captured["headers"]["X-E2E-Operator-Token"] == "operator-token"
    assert "Authorization" not in captured["headers"]


def test_append_task_message_uses_rollover_revision(monkeypatch) -> None:
    captured = {}

    class Response:
        status = 201

        @staticmethod
        def json():
            return {"active_segment_sequence": 42, "current_sequence": 43}

    monkeypatch.setattr("run_acceptance.obtain_grant", lambda *_args: "grant")
    monkeypatch.setattr(
        "run_acceptance.request",
        lambda method, url, **kwargs: captured.update(
            {"method": method, "url": url, **kwargs}
        )
        or Response(),
    )
    config = type(
        "Config",
        (),
        {
            "task_url": "https://zebra.local/tasks",
            "request_id": "request-id",
            "timeout_seconds": 30,
        },
    )()

    revision = append_task_message(config, "task/1", "run-1", "Continue safely.")

    assert revision == 42
    assert captured["method"] == "POST"
    assert captured["url"] == "https://zebra.local/tasks/task%2F1/messages"
    assert captured["headers"]["Authorization"] == "Bearer grant"
    assert captured["payload"]["reasoning_effort"] == "high"


def test_control_command_retries_a_revision_race(monkeypatch) -> None:
    seen = []

    monkeypatch.setattr("run_acceptance.task_state", lambda *_args: 10)

    def fake_command(_config, _task_id, _run_id, action, revision, input_payload):
        seen.append((action, revision, input_payload))
        if len(seen) == 1:
            from support import E2EError

            raise E2EError("http_409_revision_conflict_current_12")
        return {"status": "accepted"}

    monkeypatch.setattr("run_acceptance.command", fake_command)
    monkeypatch.setattr("run_acceptance.time.sleep", lambda _seconds: None)

    result = control_command(object(), "task", "run", "resume")

    assert result == {"status": "accepted"}
    assert [revision for _, revision, _ in seen] == [10, 12]
    assert seen[-1][2]["forwardedProps"]["expectedRevision"] == 12


def test_run_command_rebuilds_input_after_revision_race(monkeypatch) -> None:
    seen = []

    monkeypatch.setattr("run_acceptance.task_state", lambda *_args: 20)

    def fake_command(_config, _task_id, _run_id, action, revision, input_payload):
        seen.append((action, revision, input_payload))
        if len(seen) == 1:
            from support import E2EError

            raise E2EError(
                "http_409_https_zebra_invalid_problems_revision_conflict_current_22"
            )
        return {"status": "accepted"}

    monkeypatch.setattr("run_acceptance.command", fake_command)
    monkeypatch.setattr("run_acceptance.time.sleep", lambda _seconds: None)

    result = run_command(object(), "task", "run", "Continue safely.")

    assert result == {"status": "accepted"}
    assert [revision for _, revision, _ in seen] == [20, 22]
    assert seen[-1][2]["forwardedProps"]["expectedRevision"] == 22


def test_task_state_uses_active_segment_revision(monkeypatch) -> None:
    class Response:
        status = 200

        @staticmethod
        def json():
            return {"active_segment_sequence": 7, "current_sequence": 99}

    monkeypatch.setattr("support.obtain_grant", lambda *_args: "grant")
    monkeypatch.setattr("support.request", lambda *_args, **_kwargs: Response())
    config = type(
        "Config",
        (),
        {
            "task_url": "https://zebra.local/tasks",
            "request_id": "request-id",
            "timeout_seconds": 30,
        },
    )()

    assert task_state(config, "task", "run") == 7


def test_wait_task_terminal_waits_for_task_projection(monkeypatch) -> None:
    statuses = iter(("running", "awaiting_turn"))

    class Response:
        status = 200

        @staticmethod
        def json():
            return {"status": next(statuses)}

    monkeypatch.setattr("run_acceptance.obtain_grant", lambda *_args: "grant")
    monkeypatch.setattr("run_acceptance.request", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr("run_acceptance.time.sleep", lambda _seconds: None)
    config = type(
        "Config",
        (),
        {
            "task_url": "https://zebra.local/tasks",
            "request_id": "request-id",
            "timeout_seconds": 30,
        },
    )()

    wait_task_terminal(config, "task", "run")
