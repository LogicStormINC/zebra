"""Run native PG/Redis storage seams, not model/provider or browser latency.

source .artifacts/stream-baseline.env
.venv/bin/python -m tests.stream_storage.native_baseline --output .artifacts/baseline.json
Use --seconds 60 --repeats 3 for the steady matrix. Default is a fast 1/10/100
matrix. Each reader path runs independently, with live/none/degraded hints.
"""

from __future__ import annotations

import asyncio
import math
import socket
from collections import Counter
from contextlib import nullcontext
from pathlib import Path
from time import monotonic

import psycopg
from agent_core.domain.events import EventActor, EventType
from agent_integrations.ag_ui import AgUiCursor
from agent_storage.postgres.connection_pool import postgres_pool_scope
from redis import Redis
from zebra_agent_api.ag_ui_stream import prepare_agui_stream, tail_agui_events
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_streaming import tail_session_events, tail_task_events

from tests.stream_storage.native_environment import materialize, seed
from tests.stream_storage.telemetry import Telemetry, lsn_bytes, phase, server_snapshot


class Request:
    disconnected = False

    def __init__(self):
        self.ready = asyncio.Event()

    async def is_disconnected(self):
        return self.disconnected


async def consume(run, reader, fanout, request, after, metrics):
    with phase(f"reader/{reader}"):
        if reader == "session":
            source = tail_session_events(
                database_path=Path("/unused"),
                stores=run.stores,
                live_event_fanout=fanout,
                deployment_namespace=run.namespace,
                session_id=run.session_id,
                request=request,
                after_sequence=after,
            )
        elif reader == "task":
            source = tail_task_events(
                database_path=Path("/unused"),
                stores=run.stores,
                task_id=run.task_id,
                request=request,
                after_sequence=after,
            )
        else:
            query = {"runId": "run"}
            if after:
                query["cursor"] = after
            context = await asyncio.to_thread(
                prepare_agui_stream,
                run.stores,
                f"/agui/threads/{run.task_id}/runs/run/stream",
                query,
                live_event_fanout=fanout,
                deployment_namespace=run.namespace,
            )
            if context is None or isinstance(context, ApiResponse):
                raise AssertionError("native AG-UI preflight did not admit fixture")
            # Zero-frame runs admit a durable preflight before RUN_STARTED exists.
            request.ready.set()
            source = tail_agui_events(context, request)
        async for frame in source:
            metrics["frames"] += 1
            metrics["bytes"] += len(frame.encode())
            for line in frame.splitlines():
                if line.startswith("id: "):
                    metrics["cursor"] = line[4:] if reader == "agui" else int(line[4:])
            position = (
                (
                    AgUiCursor.decode(metrics["cursor"]).sequence
                    if reader == "agui"
                    else metrics["cursor"]
                )
                if metrics["cursor"]
                else -1
            )
            if (reader == "agui" and "RUN_STARTED" in frame) or (
                reader != "agui" and position >= run.initial_sequence
            ):
                request.ready.set()
            if "model_response_delta" in frame or "TEXT_MESSAGE_CONTENT" in frame:
                metrics["_content_positions"].add(position)
            if "tool_execution_completed" in frame or "TOOL_CALL_RESULT" in frame:
                metrics["_tool_positions"].add(position)
            if "text_message_content" in frame.lower() or "content_delta" in frame:
                metrics["content_frames"] += 1
            if "session_completed" in frame or "RUN_FINISHED" in frame:
                metrics["terminal_frames"] += 1


def write(run, kind, index):
    recorder = run.recorder
    with phase(f"writer/{kind}"):
        if kind == "delta":
            event_type = EventType.MODEL_RESPONSE_DELTA
            payload = {
                "model_call_id": run.model_call_id,
                "attempt_number": 1,
                "delta_index": index,
                "content_delta": "x" * 16,
            }
        elif kind == "tool":
            recorder.append(
                EventType.TOOL_CALL_PROPOSED,
                EventActor.HARNESS,
                {
                    "tool_call_id": f"synthetic-{index}",
                    "tool_name": "synthetic",
                    "arguments": {},
                    "attempt_number": 1,
                },
            )
            event_type = EventType.TOOL_EXECUTION_COMPLETED
            payload = {
                "tool_call_id": f"synthetic-{index}",
                "status": "executed",
                "metadata": {},
                "tool_name": "synthetic",
                "output": "synthetic",
                "attempt_number": 1,
            }
        elif kind == "response":
            event_type = EventType.MODEL_RESPONSE_RECEIVED
            payload = {
                "model_call_id": run.model_call_id,
                "assistant_message": "synthetic",
                "tool_call_count": 0,
                "attempt_number": 1,
            }
        else:
            event_type, payload = EventType.SESSION_COMPLETED, {"summary": "synthetic"}
        event = recorder.append(event_type, EventActor.HARNESS, payload)
    materialize(run.stores, run.task_id)
    return event.sequence


async def native_mutations(operation, arguments):
    # Shield the actual thread futures: cancelling a to_thread waiter cannot stop its commit.
    pending = asyncio.gather(
        *(asyncio.to_thread(operation, *args) for args in arguments), return_exceptions=True
    )
    try:
        results = await asyncio.shield(pending)
    except asyncio.CancelledError:
        while not pending.done():
            try:
                await asyncio.shield(pending)
            except asyncio.CancelledError:
                pass
        raise
    for result in results:
        if isinstance(result, BaseException):
            raise result
    return results


async def write_all(runs, kind, index):
    return await native_mutations(write, [(run, kind, index) for run in runs])


async def stop_consumers(requests, consumers):
    for request in requests:
        request.disconnected = True
    # Live Session may finish its native 1000ms blocking read before observing disconnect.
    await asyncio.gather(*consumers)


async def workload(dsn, client, fanout, *, reader, hint, scenario, count, seconds, cadence, pool):
    telemetry = Telemetry()
    before_server, before_wal = server_snapshot(dsn)
    started = monotonic()
    with telemetry.installed(), postgres_pool_scope(dsn) if pool else nullcontext():
        with phase("writer/admission"):
            runs = [
                (await native_mutations(seed, [(dsn, fanout, seconds)]))[0] for _ in range(count)
            ]
        metrics = [
            Counter(
                frames=0,
                bytes=0,
                cursor=0,
                content_frames=0,
                terminal_frames=0,
                _content_positions=set(),
                _tool_positions=set(),
            )
            for _ in runs
        ]
        requests = [Request() for _ in runs]
        selected = None if hint == "none" else fanout
        consumers = [
            asyncio.create_task(consume(run, reader, selected, request, 0, metric))
            for run, request, metric in zip(runs, requests, metrics, strict=True)
        ]
        for run in runs:
            run.initial_sequence = run.recorder.session.current_sequence
        try:
            await asyncio.wait_for(asyncio.gather(*(r.ready.wait() for r in requests)), 30)
        except BaseException:
            await stop_consumers(requests, consumers)
            raise
        initial_seconds = monotonic() - started
        telemetry.stage = "steady"
        steady_started = monotonic()
        deadline = steady_started + seconds
        writes, latencies, reconnected, degraded = 0, [], False, False
        expected_content, expected_tools = [set() for _ in runs], [set() for _ in runs]
        original_client, failed_client = fanout._client, None
        try:
            while monotonic() < deadline:
                if (
                    scenario == "reconnect"
                    and not reconnected
                    and monotonic() >= (steady_started + seconds / 2)
                ):
                    telemetry.stage = "reconnect"
                    await stop_consumers(requests, consumers)
                    requests = [Request() for _ in runs]
                    consumers = [
                        asyncio.create_task(
                            consume(run, reader, selected, request, metric["cursor"], metric)
                        )
                        for run, request, metric in zip(runs, requests, metrics, strict=True)
                    ]
                    await asyncio.sleep(0.1)
                    reconnected = True
                    telemetry.stage = "steady"
                if hint == "degraded" and not degraded:
                    # A real refused localhost socket, not a mocked Redis response.
                    with socket.socket() as reserved:
                        reserved.bind(("127.0.0.1", 0))
                        port = reserved.getsockname()[1]
                        failed_client = Redis(
                            host="127.0.0.1",
                            port=port,
                            socket_connect_timeout=0.1,
                            socket_timeout=0.1,
                        )
                        fanout._client = failed_client
                        degraded = True
                if scenario != "idle" and (scenario != "short" or writes == 0):
                    stamp = monotonic()
                    kind = "tool" if scenario == "tools" else "delta"
                    positions = await write_all(runs, kind, writes)
                    expected = expected_tools if kind == "tool" else expected_content
                    for wanted, position in zip(expected, positions, strict=True):
                        wanted.add(position)
                    latencies.append((monotonic() - stamp) * 1000)
                    writes += 1
                await asyncio.sleep(min(cadence, max(0, deadline - monotonic())))
            steady_seconds = monotonic() - steady_started
            if scenario == "reconnect" and not reconnected:
                telemetry.stage = "reconnect"
                await stop_consumers(requests, consumers)
                requests = [Request() for _ in runs]
                consumers = [
                    asyncio.create_task(
                        consume(run, reader, selected, request, metric["cursor"], metric)
                    )
                    for run, request, metric in zip(runs, requests, metrics, strict=True)
                ]
                await asyncio.sleep(0.1)
                reconnected = True
            telemetry.stage = "final"
            stamp = monotonic()
            if scenario != "idle":
                await write_all(runs, "response", 0)
            await write_all(runs, "terminal", 0)
            done, pending = await asyncio.wait(consumers, timeout=10)
            if pending:
                await stop_consumers(requests, consumers)
                raise AssertionError("native reader terminal convergence exceeded 10s")
            await asyncio.gather(*done)
            final_seconds = monotonic() - stamp
            terminal_converged = all(metric["terminal_frames"] > 0 for metric in metrics)
            content_converged = all(
                wanted <= metric["_content_positions"]
                for wanted, metric in zip(expected_content, metrics, strict=True)
            )
            tools_converged = all(
                wanted <= metric["_tool_positions"]
                for wanted, metric in zip(expected_tools, metrics, strict=True)
            )
        finally:
            fanout._client = original_client
            if failed_client is not None:
                failed_client.close()
            for request in requests:
                request.disconnected = True
            if any(not task.done() for task in consumers):
                await asyncio.gather(*consumers, return_exceptions=True)
    server_after, wal_after = server_snapshot(dsn)
    with psycopg.connect(dsn) as diagnostic:
        persistent = diagnostic.execute(
            "SELECT event_type,count(*),sum(event_bytes_bound),sum(pg_column_size(payload)) "
            "FROM session_events WHERE deployment_namespace=ANY(%s) GROUP BY event_type",
            ([run.namespace for run in runs],),
        ).fetchall()
    ordered = sorted(latencies)
    return {
        "reader": reader,
        "hint": hint,
        "pool_mode": "production" if pool else "none",
        "reader_uses_live_hint": reader == "session" and hint != "none",
        "persistent": {
            kind: {"events": n, "bound_bytes": int(bound), "payload_pg_bytes": int(size)}
            for kind, n, bound, size in persistent
        },
        "live_events": sum(
            client.xlen(fanout._stream_key(run.namespace, run.session_id)) for run in runs
        ),
        "scenario": scenario,
        "runs": count,
        "requested_seconds": seconds,
        "agui_initial_replay_overlap_possible": reader == "agui",
        "cadence_seconds": cadence,
        "initial_seconds": initial_seconds,
        "steady_seconds": steady_seconds,
        "final_seconds": final_seconds,
        "total_seconds": monotonic() - started,
        "writer_batches": writes,
        "writer_content_events": writes * count * (2 if scenario == "tools" else 1),
        "reconnected": reconnected,
        "redis_failure_injected": degraded,
        "native_terminal_converged": terminal_converged,
        "native_content_converged": content_converged,
        "native_tools_converged": tools_converged,
        "conformance_passed": terminal_converged and content_converged and tools_converged,
        "delivery": [
            {k: v for k, v in metric.items() if k != "cursor" and not k.startswith("_")}
            for metric in metrics
        ],
        "batch_commit_and_checkpoint_ms": {
            "samples": len(ordered),
            "p50": ordered[math.ceil(len(ordered) * 0.5) - 1] if ordered else None,
            "p95": ordered[math.ceil(len(ordered) * 0.95) - 1] if ordered else None,
        },
        "client": telemetry.report(),
        "server": {
            key: {
                metric: values[metric] - before_server.get(key, {}).get(metric, 0)
                for metric in values
            }
            for key, values in server_after.items()
        },
        "instance_wal_bytes": lsn_bytes(wal_after) - lsn_bytes(before_wal),
        "redis_owned_memory_bytes": sum(
            client.memory_usage(key) or 0
            for key in client.scan_iter(match=f"{fanout._key_prefix}:*")
        ),
    }


if __name__ == "__main__":
    from tests.stream_storage.native_runner import cli

    cli()
