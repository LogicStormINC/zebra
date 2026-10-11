"""Real scratch histories and concurrent HTTP SSE observers; no provider substitution."""

from __future__ import annotations

import asyncio
import codecs
import hashlib
import json
import ssl
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
from isolation import joint_preflight
from joint_acceptance import native_source_identity
from support import Config, E2EError, cookie_headers, decode_sse, task_binding
from terminal_probe import prove_cleanup

HISTORIES = (1_000, 10_000, 100_000)
OBSERVERS = (1, 10, 50, 100)


def validate_dimensions(history: int, observers: int) -> None:
    if type(history) is not int or history not in HISTORIES:
        raise ValueError("concurrency_history_dimension")
    if type(observers) is not int or observers not in OBSERVERS:
        raise ValueError("concurrency_observer_dimension")


def _seed_pages(dsn: str, namespace: str, task: str, floor: int, seconds: int) -> dict[str, Any]:
    """Seed lawful metadata only, retaining all native allocation/index triggers."""
    from agent_storage.postgres.command_read_state import lock_command_source
    from agent_storage.postgres.database import PostgresDatabase

    database = PostgresDatabase(dsn, deployment_namespace=namespace)
    deadline = time.monotonic() + seconds
    appended = 0
    while time.monotonic() < deadline:
        with database.connect_task_io(deadline=min(deadline, time.monotonic() + 2)) as c:
            target = c.execute(
                "SELECT active_segment_id FROM agent_tasks WHERE deployment_namespace=%s "
                "AND task_id=%s",
                (namespace, task),
            ).fetchone()
            if target is None:
                raise E2EError("concurrency_seed_task_missing")
            lock_command_source(c, namespace, target["active_segment_id"])
            row = c.execute(
                "SELECT t.active_segment_id,s.current_version,h.status "
                "FROM agent_tasks t JOIN session_streams s ON "
                "s.deployment_namespace=t.deployment_namespace "
                "AND s.session_id=t.active_segment_id "
                "JOIN session_observation_headers h ON "
                "h.deployment_namespace=t.deployment_namespace "
                "AND h.session_id=t.active_segment_id::text "
                "WHERE t.deployment_namespace=%s AND t.task_id=%s",
                (namespace, task),
            ).fetchone()
            if (
                row is None
                or row["status"] != "awaiting_turn"
                or row["active_segment_id"] != target["active_segment_id"]
            ):
                raise E2EError("concurrency_seed_requires_idle_conversation")
            session, highwater = row["active_segment_id"], row["current_version"]
            if (
                c.execute(
                    "SELECT 1 FROM worker_leases WHERE deployment_namespace=%s AND session_id=%s "
                    "AND released_at IS NULL AND expires_at>clock_timestamp() LIMIT 1",
                    (namespace, session),
                ).fetchone()
                or c.execute(
                    "SELECT 1 FROM session_command_pending WHERE deployment_namespace=%s "
                    "AND session_id=%s AND status='pending' LIMIT 1",
                    (namespace, session),
                ).fetchone()
            ):
                raise E2EError("concurrency_seed_live_execution")
            if highwater + 1 >= floor:
                return {
                    "task_id": task,
                    "session_id": str(session),
                    "history_floor": floor,
                    "actual_session_events": highwater + 1,
                    "appended_metadata": appended,
                    "canonical_final_writes": 0,
                    "page_limit": 256,
                }
            end = min(highwater + 256, floor - 1)
            # ponytail: metadata-only load isolates history size from provider input size.
            # It is not a representative semantic-conversation/context capacity test.
            c.execute(
                "INSERT INTO session_events(deployment_namespace,event_id,session_id,sequence,"
                "event_type,payload,actor,created_at) "
                "SELECT %s,md5(%s||n::text)::uuid,%s,n,'session_title_updated',"
                "jsonb_build_object('title','Bounded concurrency QA'),'system',clock_timestamp() "
                "FROM generate_series(%s::bigint,%s::bigint) n",
                (namespace, str(uuid4()), session, highwater + 1, end),
            )
            c.execute(
                "UPDATE session_streams SET current_version=%s WHERE deployment_namespace=%s "
                "AND session_id=%s AND current_version=%s",
                (end, namespace, session, highwater),
            )
            appended += end - highwater
    raise E2EError("concurrency_seed_deadline")


def seed_history(
    config: Config, conversation_key: str, history: int, *, seconds: int = 600
) -> dict[str, Any]:
    validate_dimensions(history, 1)
    if type(seconds) is not int or not 1 <= seconds <= 600:
        raise ValueError("concurrency_seed_budget")
    namespace = joint_preflight(config)["namespace_id"]
    if not isinstance(namespace, str):
        raise E2EError("concurrency_namespace_unproven")
    task, _ = task_binding(config, conversation_key=conversation_key, simple_slice=True)
    return _seed_pages(config.zebra_database_dsn, namespace, task, history, seconds)


class FrameCapture:
    """Bounded parser shares the existing SSE decoder; retain hashes, never bodies."""

    def __init__(self) -> None:
        self.cursor: str | None = None
        self.lines: list[str] = []
        self.bytes = 0
        self.frames: list[dict[str, Any]] = []

    def feed(self, line: str) -> dict[str, Any] | None:
        self.bytes += len(line.encode()) + 1
        if self.bytes > 1_048_576 or len(line.encode()) > 65_536:
            raise E2EError("concurrency_sse_byte_limit")
        if line:
            if line.startswith("id:"):
                self.cursor = line[3:].strip()
            elif line.startswith("data:"):
                self.lines.append(line[5:].lstrip())
            return None
        event = decode_sse(self.cursor, self.lines)
        self.cursor, self.lines = None, []
        if event is None:
            return None
        if not event.cursor or not event.cursor.isdecimal():
            raise E2EError("concurrency_unpositioned_problem")
        cursor = int(event.cursor)
        if (self.frames and cursor <= self.frames[-1]["cursor"]) or len(self.frames) >= 256:
            raise E2EError("concurrency_sse_cursor_or_frame_limit")
        frame = {
            "cursor": cursor,
            "answer_committed": event.data.get("answer_committed") is True,
            "payload_sha256": hashlib.sha256(
                json.dumps(
                    dict(event.data), sort_keys=True, ensure_ascii=False, separators=(",", ":")
                ).encode()
            ).hexdigest(),
        }
        self.frames.append(frame)
        return frame

    def finish(self) -> None:
        if self.lines or self.cursor is not None:
            raise E2EError("concurrency_truncated_sse")


async def _observe(
    client: httpx.AsyncClient,
    url: str,
    index: int,
    *,
    slow: bool,
    opened: asyncio.Queue[int],
    read_gate: asyncio.Event,
    fast_done: asyncio.Event,
    started: float,
) -> dict[str, Any]:
    capture = FrameCapture()
    async with client.stream("GET", url, headers={"Accept": "text/event-stream"}) as response:
        if response.status_code != 200 or "text/event-stream" not in response.headers.get(
            "content-type", ""
        ):
            raise E2EError("concurrency_stream_rejected")
        opened.put_nowait(index)
        await read_gate.wait()
        if slow:
            # No body reads until EVERY healthy client receives the actual committed final.
            await fast_done.wait()
        decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        pending = ""
        received = 0
        async for chunk in response.aiter_bytes():
            received += len(chunk)
            if received > 1_048_576:
                raise E2EError("concurrency_sse_byte_limit")
            pending += decoder.decode(chunk)
            while "\n" in pending:
                line, pending = pending.split("\n", 1)
                frame = capture.feed(line.rstrip("\r"))
                if frame and frame["answer_committed"]:
                    return {
                        "observer": index,
                        "slow": slow,
                        "opened": True,
                        "final_receipt_ms": (time.monotonic() - started) * 1000,
                        "frames": capture.frames,
                        "body_bytes": received,
                    }
            if len(pending.encode()) > 65_536:
                raise E2EError("concurrency_sse_byte_limit")
        pending += decoder.decode(b"", final=True)
        if pending:
            raise E2EError("concurrency_truncated_sse")
        capture.finish()
    raise E2EError("concurrency_final_missing")


def validate_concurrency(evidence: dict[str, Any]) -> None:
    validate_dimensions(evidence["history_floor"], evidence["observer_count"])
    rows = evidence["observers"]
    fast = [row for row in rows if row.get("slow") is False]
    slow = [row for row in rows if row.get("slow") is True]
    expected_fast = max(1, evidence["observer_count"] - 1)
    if (
        len(rows) != evidence["observer_count"]
        or len(fast) != expected_fast
        or len(slow) != int(evidence["observer_count"] > 1)
        or {row["observer"] for row in rows} != set(range(len(rows)))
        or evidence.get("all_headers_before_terminal") is not True
        or evidence.get("provider_substitution") is not False
        or evidence["history"]["actual_session_events"] < evidence["history_floor"]
        or evidence["history"].get("canonical_final_writes") != 0
    ):
        raise E2EError("concurrency_evidence_incomplete")
    signatures = []
    for row in rows:
        finals = [frame for frame in row["frames"] if frame.get("answer_committed") is True]
        if len(finals) != 1 or row.get("opened") is not True or row["body_bytes"] > 1_048_576:
            raise E2EError("concurrency_observer_final")
        signatures.append((finals[0]["cursor"], finals[0]["payload_sha256"]))
    if len(set(signatures)) != 1 or any(
        row["final_receipt_ms"] <= evidence["healthy_final_ms"] for row in slow
    ):
        raise E2EError("concurrency_slow_isolation_unproven")
    if (
        evidence["cleanup"].get("status") != "passed"
        or not 0 <= evidence["cleanup_after_final_ms"] <= 5000
    ):
        raise E2EError("concurrency_cleanup_unproven")


async def run_concurrency_case(
    config: Config, conversation_key: str, *, history: int, observers: int
) -> dict[str, Any]:
    """Main runner seam: one actual Turn, N HTTP observers, bounded native cleanup."""
    validate_dimensions(history, observers)
    joint_preflight(config)
    identity = await asyncio.to_thread(native_source_identity, config)
    if not identity or any(
        not isinstance(role, dict) or role.get("current_checkout_match") is not True
        for role in identity.values()
    ):
        raise E2EError("concurrency_frozen_source_not_current")
    seeded = await asyncio.to_thread(seed_history, config, conversation_key, history)
    started = time.monotonic()
    verify = ssl.create_default_context()
    headers = cookie_headers(config)
    base = config.bff_url.rstrip("/") + "/api/trench-ai"
    async with asyncio.timeout(config.timeout_seconds):
        async with httpx.AsyncClient(
            verify=verify,
            trust_env=False,
            headers=headers,
            limits=httpx.Limits(max_connections=observers + 2),
            timeout=config.timeout_seconds,
        ) as client:
            response = await client.post(
                base + "/conversations/" + quote(conversation_key, safe="") + "/turns",
                json={
                    "message": "请简短说明为什么慢观察客户端不应阻塞其他观察者。不要调用工具。",
                    "client_request_id": "bounded-concurrency-" + uuid4().hex,
                    "capability_mode": "general",
                    "reasoning_effort": "none",
                    "auto_select_skills": False,
                },
            )
            if response.status_code != 202:
                raise E2EError("concurrency_turn_admission_rejected")
            turn = response.json()["data"]["turn"]
            UUID(turn["turn_id"])
            url = base + "/turns/" + quote(turn["turn_id"], safe="")
            opened: asyncio.Queue[int] = asyncio.Queue()
            gate, fast_done = asyncio.Event(), asyncio.Event()
            async with asyncio.TaskGroup() as group:
                tasks = [
                    group.create_task(
                        _observe(
                            client,
                            url + "/events",
                            index,
                            slow=observers > 1 and index == observers - 1,
                            opened=opened,
                            read_gate=gate,
                            fast_done=fast_done,
                            started=started,
                        )
                    )
                    for index in range(observers)
                ]
                for _ in tasks:
                    await opened.get()
                snapshot = await client.get(url)
                if snapshot.status_code != 200 or snapshot.json()["data"]["turn"]["status"] not in {
                    "accepted",
                    "queued",
                    "dispatching",
                    "running",
                }:
                    raise E2EError("concurrency_observers_not_live")
                gate.set()
                fast = tasks[:-1] if observers > 1 else tasks
                await asyncio.gather(*fast)
                healthy_final = time.monotonic()
                cleanup_task = group.create_task(
                    asyncio.to_thread(prove_cleanup, config, conversation_key, turn["run_id"])
                )
                fast_done.set()
            evidence = {
                "scope": "real_scratch_http_sse",
                "history_floor": history,
                "observer_count": observers,
                "history": seeded,
                "provider_substitution": False,
                "all_headers_before_terminal": True,
                "observers": [task.result() for task in tasks],
                "healthy_final_ms": (healthy_final - started) * 1000,
                "slow_client_basis": "no_body_reads_until_all_healthy_finals_not_socket_saturation",
                "cleanup": cleanup_task.result(),
                "cleanup_after_final_ms": (time.monotonic() - healthy_final) * 1000,
                "run_id": turn["run_id"],
                "turn_id": turn["turn_id"],
                "full_goal_passed": False,
                "source_identity": identity,
            }
    validate_concurrency(evidence)
    return evidence


async def run_concurrency_matrix(config: Config, conversation_key: str, output: Path) -> None:
    """Incremental evidence: a missing/failed cell never counts as matrix completion."""
    output.mkdir(parents=True, exist_ok=False)
    for history in HISTORIES:
        for observers in OBSERVERS:
            evidence = await run_concurrency_case(
                config, conversation_key, history=history, observers=observers
            )
            (output / f"history-{history}-observers-{observers}.json").write_text(
                json.dumps(evidence, indent=2) + "\n"
            )
