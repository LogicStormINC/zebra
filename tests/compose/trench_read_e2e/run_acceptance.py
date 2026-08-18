"""Fail-closed real-service acceptance for the Trench read-only slice."""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import cast
from urllib.parse import quote

from support import (  # type: ignore[import-not-found]
    Config,
    ConfigError,
    E2EError,
    SseEvent,
    bootstrap,
    business_snapshot,
    cookie_headers,
    join_url,
    load_config,
    obtain_grant,
    read_manifest_and_event,
    request,
    require_status,
    run_input,
    sse_events,
    task_state,
)

MANIFEST = Path(__file__).with_name("runner_manifest.json")
SCHEMA_VERSION = "zebra.trench-read-e2e.result.v1"
REQUIRED_ENV = (
    "TRENCH_E2E_BFF_URL",
    "TRENCH_E2E_READ_TOOLS_URL",
    "TRENCH_E2E_SESSION_COOKIE",
    "TRENCH_E2E_EVENT_ID",
    "TRENCH_E2E_HEALTH_URL",
    "TRENCH_E2E_DATABASE_DSN",
    "TRENCH_E2E_REDIS_URL",
    "TRENCH_E2E_OBJECT_STORE_HEALTH_URL",
    "TRENCH_E2E_BUSINESS_SNAPSHOT_URL",
    "ZEBRA_E2E_BASE_URL",
    "ZEBRA_E2E_HEALTH_URL",
    "ZEBRA_E2E_DATABASE_DSN",
    "ZEBRA_E2E_REDIS_URL",
    "ZEBRA_E2E_OBJECT_STORE_HEALTH_URL",
    "ZEBRA_E2E_GRANT_EXCHANGE_URL",
    "ZEBRA_E2E_WORKER_RESTART_URL",
)
SCENARIOS = (
    "infrastructure",
    "read_task",
    "long_task",
    "disconnect_replay",
    "worker_restart",
    "stop_resume",
    "grant_replay",
    "host_tool_failure",
    "zero_writes",
)
READ_TOOL_NAMES = {
    "events.get_event",
    "events.get_evidence",
    "events.get_related_events",
    "events.get_entity_timeline",
    "events.get_topic",
}
TERMINAL_EVENT_TYPES = {
    "RUN_FINISHED",
    "RUN_ERROR",
    "RUN_FAILED",
    "RUN_CANCELLED",
    "RUN_STOPPED",
}


def bff_run(
    config: Config, task_id: str, run_id: str, prompt: str, revision: int
) -> list[SseEvent]:
    return cast(
        list[SseEvent],
        sse_events(
            "POST",
            join_url(config.bff_url, "/api/copilotkit-zebra/agent/zebra/run"),
            headers={**cookie_headers(config), "Accept": "text/event-stream"},
            payload=run_input(task_id, run_id, prompt, revision),
            timeout=config.timeout_seconds,
        ),
    )


def command(
    config: Config,
    task_id: str,
    run_id: str,
    action: str,
    expected_revision: int,
    input_payload: Mapping[str, object] | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "action": action,
        "threadId": task_id,
        "runId": run_id,
        "expectedRevision": expected_revision,
    }
    if input_payload is not None:
        body["input"] = dict(input_payload)
    grant = obtain_grant(config, task_id, run_id)
    key_hash = sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    response = request(
        "POST",
        config.command_url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {grant}",
            "Content-Type": "application/json",
            "Idempotency-Key": f"trench-e2e-{key_hash}",
            "X-Trench-Request-Id": config.request_id,
        },
        payload=body,
        timeout=config.timeout_seconds,
    )
    require_status(response, {200, 202})
    result = response.json()
    if not isinstance(result, dict) or result.get("status") not in {"accepted", "duplicate"}:
        raise E2EError("command_not_accepted")
    return result


def direct_stream(
    config: Config,
    task_id: str,
    run_id: str,
    cursor: str | None = None,
    stop_after: int | None = None,
) -> list[SseEvent]:
    grant = obtain_grant(config, task_id, run_id)
    stream_url = (
        f"{config.zebra_base_url}/agui/threads/{quote(task_id, safe='')}"
        f"/runs/{quote(run_id, safe='')}/stream"
    )
    return cast(
        list[SseEvent],
        sse_events(
            "GET",
            stream_url,
            headers={
                "Accept": "text/event-stream",
                "Authorization": f"Bearer {grant}",
                "X-Trench-Request-Id": config.request_id,
            },
            payload=None,
            timeout=config.timeout_seconds,
            cursor=cursor,
            stop_after=stop_after,
        ),
    )


def worker_restart(config: Config, task_id: str, run_id: str) -> None:
    headers = {"Accept": "application/json", "X-Trench-Request-Id": config.request_id}
    if config.operator_token:
        headers["Authorization"] = f"Bearer {config.operator_token}"
    response = request(
        "POST",
        config.worker_restart_url,
        headers=headers,
        payload={"taskId": task_id, "runId": run_id},
        timeout=config.timeout_seconds,
    )
    require_status(response, set(range(200, 300)))


def _scenario_infrastructure(config: Config, state: dict[str, object]) -> None:
    from support import health, postgres_probe, redis_probe

    urls = (
        config.trench_health_url,
        config.zebra_health_url,
        config.trench_object_store_url,
        config.zebra_object_store_url,
    )
    for url in urls:
        health(url, config.timeout_seconds)
    postgres_probe(config.trench_database_dsn)
    postgres_probe(config.zebra_database_dsn)
    redis_probe(config.trench_redis_url)
    redis_probe(config.zebra_redis_url)
    state["snapshot_before"] = business_snapshot(config)


def _scenario_read_task(config: Config, state: dict[str, object]) -> None:
    read_manifest_and_event(config, READ_TOOL_NAMES)
    task_id = bootstrap(config)
    state["task_id"] = task_id
    state["revision"] = task_state(config, task_id, "bootstrap")


def _require_task(state: Mapping[str, object]) -> tuple[str, int]:
    task_id = state.get("task_id")
    revision = state.get("revision")
    if not isinstance(task_id, str) or not isinstance(revision, int):
        raise E2EError("dependency_read_task")
    return task_id, revision


def _scenario_long_task(config: Config, state: dict[str, object]) -> None:
    task_id, revision = _require_task(state)
    run_id = f"long-{uuid.uuid4()}"
    prompt = os.environ.get(
        "TRENCH_E2E_LONG_PROMPT",
        "Read the selected event and return a bounded summary.",
    )
    events = bff_run(config, task_id, run_id, prompt, revision)
    if not any(event.data.get("type") in TERMINAL_EVENT_TYPES for event in events):
        raise E2EError("long_task_not_terminal")
    state["long_run_id"] = run_id


def _scenario_disconnect_replay(config: Config, state: dict[str, object]) -> None:
    task_id, _ = _require_task(state)
    run_id = state.get("long_run_id")
    if not isinstance(run_id, str):
        raise E2EError("dependency_long_task")
    first = direct_stream(config, task_id, run_id, stop_after=1)
    cursor = next((event.cursor for event in first if event.cursor), None)
    if cursor is None:
        raise E2EError("stream_cursor_missing")
    replay = direct_stream(config, task_id, run_id, cursor)
    if not replay or any(event.cursor == cursor for event in replay):
        raise E2EError("replay_cursor_not_advanced")


def _scenario_worker_restart(config: Config, state: dict[str, object]) -> None:
    task_id, _ = _require_task(state)
    revision = task_state(config, task_id, "restart")
    run_id = f"restart-{uuid.uuid4()}"
    input_payload = run_input(task_id, run_id, "Run a bounded read-only task.", revision)
    command(config, task_id, run_id, "run", revision, input_payload)
    worker_restart(config, task_id, run_id)
    events = direct_stream(config, task_id, run_id)
    if not any(event.data.get("type") in TERMINAL_EVENT_TYPES for event in events):
        raise E2EError("worker_restart_not_recovered")


def _scenario_stop_resume(config: Config, state: dict[str, object]) -> None:
    task_id, _ = _require_task(state)
    run_id = f"control-{uuid.uuid4()}"
    revision = task_state(config, task_id, run_id)
    input_payload = run_input(task_id, run_id, "Start a bounded read-only task.", revision)
    run_result = command(config, task_id, run_id, "run", revision, input_payload)
    event_sequence = run_result.get("event_sequence")
    stop_revision = (
        event_sequence if isinstance(event_sequence, int) else task_state(config, task_id, run_id)
    )
    command(config, task_id, run_id, "stop", stop_revision)
    resume_revision = task_state(config, task_id, run_id)
    resume_input = run_input(task_id, run_id, "Resume the bounded read-only task.", resume_revision)
    resume_input["resume"] = [{"interruptId": "e2e-control", "status": "resolved"}]
    command(config, task_id, run_id, "resume", resume_revision, resume_input)


def _scenario_grant_replay(config: Config, state: dict[str, object]) -> None:
    task_id, _ = _require_task(state)
    run_id = f"grant-replay-{uuid.uuid4()}"
    grant = obtain_grant(config, task_id, run_id)
    url = f"{config.task_url}/{task_id}"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {grant}",
        "X-Trench-Request-Id": config.request_id,
    }
    first = request("GET", url, headers=headers, timeout=config.timeout_seconds)
    require_status(first, {200})
    replay = request("GET", url, headers=headers, timeout=config.timeout_seconds)
    if replay.status not in {401, 403}:
        raise E2EError("grant_replay_accepted")


def _scenario_host_tool_failure(config: Config, _state: dict[str, object]) -> None:
    response = request(
        "POST",
        join_url(config.read_tools_url, "/tools/events.get_event/invoke"),
        headers={**cookie_headers(config), "X-Zebra-Workload-Identity": "trench-read-only"},
        payload={"toolName": "events.get_event", "arguments": {"event_id": ""}},
        timeout=config.timeout_seconds,
    )
    if response.status not in {400, 422}:
        raise E2EError("host_tool_failure_not_bounded")


def _scenario_zero_writes(config: Config, state: dict[str, object]) -> None:
    before = state.get("snapshot_before")
    if not isinstance(before, str):
        raise E2EError("dependency_snapshot")
    if before != business_snapshot(config):
        raise E2EError("trench_business_snapshot_changed")


def _write_result(evidence_dir: Path, result: Mapping[str, object]) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _run(evidence_dir: Path) -> int:
    result: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "runner": "EMB-TRN-READ-E2E-01",
        "scenarios": {},
        "passed": False,
    }
    try:
        config = load_config(os.environ, REQUIRED_ENV)
    except ConfigError as error:
        result.update(
            {
                "status": "blocked",
                "missing_environment": error.missing,
                "invalid_environment": error.invalid,
            }
        )
        _write_result(evidence_dir, result)
        print("ZEBRA_TRENCH_READ_E2E=BLOCKED")
        return 2
    state: dict[str, object] = {}
    functions = {
        "infrastructure": _scenario_infrastructure,
        "read_task": _scenario_read_task,
        "long_task": _scenario_long_task,
        "disconnect_replay": _scenario_disconnect_replay,
        "worker_restart": _scenario_worker_restart,
        "stop_resume": _scenario_stop_resume,
        "grant_replay": _scenario_grant_replay,
        "host_tool_failure": _scenario_host_tool_failure,
        "zero_writes": _scenario_zero_writes,
    }
    failures = 0
    scenarios: dict[str, object] = {}
    result["scenarios"] = scenarios
    for name in SCENARIOS:
        started = time.monotonic()
        try:
            functions[name](config, state)
        except E2EError as error:
            failures += 1
            scenarios[name] = {
                "status": "failed",
                "reason": error.code,
                "duration_seconds": round(time.monotonic() - started, 3),
            }
            print(f"{name}=FAIL reason={error.code}")
        except Exception:
            failures += 1
            scenarios[name] = {
                "status": "failed",
                "reason": "unexpected_runner_error",
                "duration_seconds": round(time.monotonic() - started, 3),
            }
            print(f"{name}=FAIL reason=unexpected_runner_error")
        else:
            scenarios[name] = {
                "status": "passed",
                "duration_seconds": round(time.monotonic() - started, 3),
            }
            print(f"{name}=PASS")
    result.update({"status": "passed" if failures == 0 else "failed", "passed": failures == 0})
    _write_result(evidence_dir, result)
    print(f"ZEBRA_TRENCH_READ_E2E={'PASS' if failures == 0 else 'FAIL'}")
    return 0 if failures == 0 else 1


def _list_manifest() -> int:
    document = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for scenario in document["scenarios"]:
        print(scenario["id"])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()
    if args.list:
        return _list_manifest()
    evidence_dir = args.evidence_dir or Path(
        os.environ.get("ZEBRA_TRENCH_READ_E2E_EVIDENCE_DIR", "trench-read-e2e-evidence")
    )
    return _run(evidence_dir)


if __name__ == "__main__":
    raise SystemExit(main())
