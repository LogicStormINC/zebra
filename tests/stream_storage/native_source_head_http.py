"""Real signed loopback SSE, one Run; native Recorder/Turn/Consumer; no Worker/SDK."""

import argparse
import asyncio
import json
import os
import re
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from time import monotonic, thread_time
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
import pytest
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelTextDelta
from agent_core.harness.model_step import HarnessModelStep
from agent_core.harness.models import HarnessEventDraft
from agent_security import PyJwtHostGrantDecoder
from agent_storage import PostgresHostAuthorityStore
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.projection_work import PostgresTaskProjectionWorkStore
from cryptography.hazmat.primitives.asymmetric import rsa
from zebra_agent_api import create_http_app
from zebra_agent_api.host_auth import PostgresHostGrantRequestAuthorizer
from zebra_agent_api.http import HostGrantHttpRequest
from zebra_agent_config.settings import LiveEventSettings
from zebra_agent_config.stream_settings import StreamSettings
from zebra_agent_worker.transient_output_composition import compose_transient_output_factory

from tests.agent_storage.test_postgres_http_auth_boundary_e2e import _http_socket
from tests.api.test_postgres_host_auth_authorizer import (
    _claims,
    _registry,
    _settings,
    _StaticResolver,
)
from tests.api.test_stream_v2_native import materialize
from tests.stream_storage.native_environment import native_environment
from tests.stream_storage.native_source_head_diagnostics import (
    api_loop_probe,
    capture_asgi_exception,
    failure_diagnostics,
    install_diagnostics,
)
from tests.stream_storage.telemetry import Telemetry, phase
from tests.test_cloud_api_worker_profile_composition import _cloud_settings
from tests.worker import test_transient_output_composition_native as composition


def signed_authority(dsn, namespace):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    registry = PostgresHostAuthorityStore(dsn, deployment_namespace=namespace)
    record = _registry()
    registry.upsert_registry(record)
    authorizer = PostgresHostGrantRequestAuthorizer(
        registry=registry, decoder=PyJwtHostGrantDecoder(_StaticResolver(key.public_key()))
    )

    def headers():
        claims = _claims(
            uuid4().hex,
            scopes=["agent.run", "event.read"],
            exp=int(datetime.now(UTC).timestamp()) + 900,
        )
        claims["limits"]["max_runtime_seconds"] = 1800
        claims["resource_refs"] = [
            {"type": "principal", "id": "opaque-subject"},
            {"type": "thread", "id": "owned-http-head-thread"},
            {"type": "run", "id": "run-v2"},
        ]
        return {
            "Authorization": "Bearer " + jwt.encode(claims, key, algorithm="RS256"),
            "Origin": record.allowed_origins[0],
        }

    verified = authorizer.authorize(
        HostGrantHttpRequest(
            method="GET",
            path="/sessions",
            authorization=headers()["Authorization"],
            origin=record.allowed_origins[0],
        )
    )
    return authorizer, headers, verified


def fixture(owned, monkeypatch, mode):
    from tests.stream_storage import native_environment as environment

    epoch = environment.bootstrap_control_plane_epoch
    bootstrap = environment.SessionBootstrapCommand
    captured = {}

    def initialize(dsn, *, deployment_namespace):
        epoch(dsn, deployment_namespace=deployment_namespace)
        authorizer, headers, verified = signed_authority(dsn, deployment_namespace)
        captured.update(authorizer=authorizer, headers=headers, verified=verified)
        monkeypatch.setattr(composition, "_context", lambda: verified.context)
        monkeypatch.setattr(composition, "_verified", lambda context: verified)

    monkeypatch.setattr(environment, "bootstrap_control_plane_epoch", initialize)
    monkeypatch.setattr(
        environment,
        "SessionBootstrapCommand",
        lambda **kwargs: bootstrap(
            host_context=captured["verified"].context,
            **kwargs,
        ),
    )
    run, lease, recovery, binding, settings = composition.setup(owned, monkeypatch)
    queue = PostgresTaskProjectionWorkStore(
        PostgresDatabase(owned[0], deployment_namespace=run.namespace), "ag-ui-v1"
    )
    queue.enable_projection_work()
    run.stores.projection_work = queue
    recovery.persist_with(run.recorder.append_draft)(
        HarnessEventDraft(
            EventType.PUBLIC_OUTPUT,
            EventActor.HARNESS,
            {
                "attempt_number": 1,
                "output_id": "idle-status",
                "kind": "status",
                "phase": "waiting",
                "origin": "system",
                "content": "Working",
            },
        )
    )
    stopped, ready = threading.Event(), threading.Event()
    writer, thread = None, None
    failures = []
    if mode == "paused":
        writer = compose_transient_output_factory(
            run.stores, dsn=owned[0], namespace=run.namespace, settings=settings
        )(recovery, lease)

        class Provider:
            def complete_stream(self, _messages, *, tools=(), on_text_delta):
                on_text_delta(ModelTextDelta(index=0, content="Owned paused draft"))
                ready.set()
                stopped.wait()
                return ModelCompletion(
                    assistant_message=SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.ASSISTANT,
                        content="Owned pause finished",
                        created_at=datetime.now(UTC),
                    )
                )

        def model():
            try:
                HarnessModelStep(
                    event_sink=writer.wrap(recovery.persist_with(run.recorder.append_draft)),
                    public_call_started=writer.start_public_call,
                ).request_completion([], Provider(), allow_tools=True)
            except BaseException as exc:
                failures.append(type(exc).__name__)
                ready.set()

        thread = threading.Thread(target=model)
        thread.start()
        assert ready.wait(10) and not failures and not writer._failed
    materialize(run.stores, run.task_id, owned)
    cloud = replace(_cloud_settings(), dsn=owned[0], deployment_namespace=run.namespace)
    api_settings = replace(
        _settings(owned[0]),
        live_events=LiveEventSettings(redis_url=owned[3], key_prefix=owned[2]._key_prefix),
        stream=StreamSettings(cursor_signing_key=b"owned-source-head-http-shared-key-32"),
    )
    # Only isolate the Redis key prefix; all production authority predicates run.
    from zebra_agent_api import factory as api_factory

    authority = api_factory.V2ReadAuthority
    monkeypatch.setattr(
        api_factory,
        "V2ReadAuthority",
        lambda *args, **kwargs: authority(
            *args, **kwargs, key_prefix=f"{owned[2]._key_prefix}:admission"
        ),
    )

    read_timings, timing_lock, server_peers = {}, threading.Lock(), {}
    admission_timings = install_diagnostics(monkeypatch, captured, read_timings, timing_lock)

    def app_factory():
        app = create_http_app(
            Path("/unused"),
            settings=api_settings,
            cloud_composition=cloud,
            host_grant_authorizer=captured["authorizer"],
        )

        async def measured(scope, receive, send):
            if scope["type"] == "lifespan":
                async with api_loop_probe(admission_timings):
                    await app(scope, receive, send)
                return
            headers = dict(scope.get("headers", ()))
            label = headers.get(b"x-source-head-attempt", b"lifespan").decode()
            peer = scope.get("client")
            if peer and peer[0] in {"127.0.0.1", "::1"}:
                with timing_lock:
                    server_peers[label] = peer[1]
            with phase("http/" + label):
                await capture_asgi_exception(
                    app, scope, receive, send, admission_timings, timing_lock
                )

        return measured

    progress_id = "reconnect-status-" + str(uuid4())

    def progress():
        recovery.persist_with(run.recorder.append_draft)(
            HarnessEventDraft(
                EventType.PUBLIC_OUTPUT,
                EventActor.HARNESS,
                {
                    "attempt_number": 1,
                    "output_id": progress_id,
                    "kind": "status",
                    "phase": "waiting",
                    "origin": "system",
                    "content": "Resumed",
                },
            )
        )
        materialize(run.stores, run.task_id, owned)

    return SimpleNamespace(
        app_factory=app_factory,
        progress=progress,
        progress_id=progress_id,
        read_timings=read_timings,
        admission_timings=admission_timings,
        run=run,
        headers=captured["headers"],
        lease=lease,
        stopped=stopped,
        thread=thread,
        writer=writer,
        failures=failures,
        admission_errors=[],
        server_peers=server_peers,
    )


async def subscribe(base, state, route, index, results, client):
    path = {
        "session": f"/sessions/{state.run.session_id}/stream",
        "task": f"/tasks/{state.run.task_id}/stream",
        "agui": f"/agui/threads/{state.run.task_id}/runs/run-v2/stream",
    }[route]
    cursor, reconnects, frames, connected_seconds, notices = None, 0, 0, 0.0, {}
    record_cursor, record_names, reconnect_cursor = None, [], None
    record_progress, record_heartbeat = False, False
    stop = asyncio.create_task(state.stop.wait())
    reconnect = asyncio.create_task(state.reconnect.wait())
    try:
        while not state.stop.is_set():
            headers = state.headers()
            headers["X-Source-Head-Attempt"] = (
                "initial" if reconnects == 0 else "reconnect"
            ) + f"/{index}"
            if cursor is not None:
                headers["Last-Event-ID"] = cursor
            async with client.stream(
                "GET", path + ("?recovery=full" if reconnects == 0 else ""), headers=headers
            ) as response:
                if response.status_code != 200:
                    try:
                        raw = await anext(response.aiter_bytes(chunk_size=4097), b"")
                        body = json.loads(raw) if len(raw) <= 4096 else {}
                    except (ValueError, httpx.HTTPError):
                        body = {}
                    allowed = {}
                    if isinstance(body, dict):
                        for key in ("status", "reason", "retryable"):
                            value = body.get(key)
                            if (
                                type(value) is bool
                                or isinstance(value, str)
                                and re.fullmatch(r"[a-z0-9_]{1,80}", value)
                            ):
                                allowed[key] = value
                    state.admission_errors.append(
                        {"index": index, "http_status": response.status_code, **allowed}
                    )
                    raise AssertionError(f"HTTP admission {response.status_code}")
                connected = monotonic()
                state.admitted[index] = True
                if reconnects:
                    state.reconnected[index] = monotonic()
                lines, pending = response.aiter_lines(), None
                try:
                    while not state.stop.is_set():
                        pending = asyncio.create_task(anext(lines))
                        await asyncio.wait(
                            {pending, stop} | ({reconnect} if reconnects == 0 else set()),
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if stop.done():
                            break
                        if reconnects == 0 and reconnect.done():
                            reconnect_cursor, reconnects = cursor, 1
                            record_cursor, record_names, record_progress = None, [], False
                            record_heartbeat = False
                            break
                        try:
                            line = pending.result()
                        except StopAsyncIteration:
                            raise AssertionError(
                                "HTTP stream closed before observation deadline"
                            ) from None
                        pending = None
                        record_heartbeat |= line.startswith(":")
                        if line.startswith("id: "):
                            record_cursor = line[4:]
                        if line.startswith("data: "):
                            event = json.loads(line[6:])
                            name = event.get("name")
                            payload = event.get("payload") or event.get("value") or {}
                            record_progress |= (
                                isinstance(payload, dict)
                                and payload.get("output_id") == state.progress_id
                                and payload.get("content") == "Resumed"
                                and (
                                    event.get("event_type") == "public_output"
                                    or name == "zebra.public_output"
                                )
                                and bool(payload.get("event_id") or event.get("event_id"))
                            )
                            if name:
                                record_names.append(name)
                        if not line:
                            frames += 1
                            if record_cursor is not None:
                                cursor = record_cursor
                            for name in record_names:
                                notices[name] = notices.get(name, 0) + 1
                                if name == "zebra.stream.recovery_complete" and not reconnects:
                                    state.recovered[index] = True
                            if reconnects and (
                                record_progress
                                and cursor is not None
                                and cursor != reconnect_cursor
                                or state.timeline == "idle_resume"
                                and record_heartbeat
                                and reconnect_cursor is not None
                            ):
                                state.resume_ready[index] = monotonic()
                            record_cursor, record_names, record_progress = None, [], False
                            record_heartbeat = False
                finally:
                    connected_seconds += monotonic() - connected
                    if pending is not None:
                        pending.cancel()
                        await asyncio.gather(pending, return_exceptions=True)
        results[index] = {
            "seconds": connected_seconds,
            "frames": frames,
            "reconnects": reconnects,
            "notices": notices,
            "reconnect_connected_at": state.reconnected[index],
            "reconnect_ready_at": state.resume_ready[index],
        }
    finally:
        stop.cancel()
        reconnect.cancel()
        await asyncio.gather(stop, reconnect, return_exceptions=True)


async def observe(base, state, route, count, seconds, timeline):
    results = [None] * count
    state.stop, state.reconnect, state.admitted = asyncio.Event(), asyncio.Event(), [False] * count
    state.recovered = [False] * count
    state.timeline = timeline
    state.reconnected, state.resume_ready = [None] * count, [None] * count
    startup = monotonic()
    cpu_started, admission_finished, admission_cpu = thread_time(), None, None
    consumers = []
    async with httpx.AsyncClient(
        base_url=base,
        timeout=httpx.Timeout(40, connect=10),
        trust_env=False,
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=100),
    ) as client:
        try:
            for index in range(count):
                state.admission_timings.append(
                    {"kind": "issued", "index": index, "at": monotonic()}
                )
                consumers.append(
                    asyncio.create_task(subscribe(base, state, route, index, results, client))
                )
                # Admission ramp is included in costs; this is not a TTFT acceptance gate.
                await asyncio.sleep(0.025)
            while not (all(state.admitted) and all(state.recovered)):
                for consumer in consumers:
                    if consumer.done():
                        await consumer
                if monotonic() - startup > 60:
                    raise AssertionError("not every subscriber admitted within startup bound")
                await asyncio.sleep(0.01)
            admission_finished, admission_cpu = monotonic(), thread_time()
            ports = {state.server_peers[f"initial/{index}"] for index in range(count)}
            assert len(ports) == count, "every admitted SSE must have an independent TCP connection"
            state.admission_timings.append(
                {"kind": "server-peers", "count": len(ports), "ports": sorted(ports)}
            )
            with state.telemetry.lock:
                state.startup_calls = dict(state.telemetry.calls)
            started = state.steady_started = monotonic()
            if timeline != "healthy":
                asyncio.get_running_loop().call_later(seconds / 2, state.reconnect.set)

            def stop_window():
                state.steady_ended = monotonic()
                state.stop.set()

            asyncio.get_running_loop().call_later(seconds, stop_window)
            renewals, progressed = 0, False
            while not state.stop.is_set():
                for consumer in consumers:
                    if consumer.done():
                        await consumer
                if timeline == "resume" and all(state.reconnected) and not progressed:
                    with phase("producer/reconnect-progress"):
                        await asyncio.to_thread(state.progress)
                    progressed = True
                if monotonic() - startup >= (renewals + 1) * 180:
                    state.lease = await asyncio.to_thread(
                        state.run.stores.leases.heartbeat,
                        state.run.session_id,
                        fence=state.lease.fence,
                        ttl=timedelta(seconds=300),
                        checkpoint=state.lease.checkpoint,
                    )
                    renewals += 1
                    state.completed_lease_heartbeats = renewals
                await asyncio.sleep(0.1)
            await asyncio.gather(*consumers)
            if timeline == "idle_resume":
                with state.telemetry.lock:
                    calls = dict(state.telemetry.calls)
                for index in range(count):
                    assert any(
                        f"http/reconnect/{index}/" in key
                        and "/sql:" in key
                        and ("/qualified-head/" in key or "/qualified-source/" in key)
                        for key in calls
                    ), "each resumed request must freshly qualify canonical source"
            if timeline != "healthy" and not all(state.resume_ready):
                raise AssertionError("every resumed subscriber must ACK complete newer progress")
            return results, renewals, monotonic() - started
        finally:
            state.observation_exited = monotonic()
            state.admission_timings.append(
                {
                    "kind": "client-admission-loop",
                    "seconds": (admission_finished or monotonic()) - startup,
                    "thread_cpu_seconds": (admission_cpu or thread_time()) - cpu_started,
                    "completed_barrier": admission_finished is not None,
                }
            )
            state.stop.set()
            for consumer in consumers:
                consumer.cancel()
            await asyncio.gather(*consumers, return_exceptions=True)


def fingerprints():
    root = Path(__file__).resolve().parents[2]
    files = sorted(
        path for folder in ("apps", "packages") for path in (root / folder).rglob("*.py")
    )
    files.append(Path(__file__).resolve())
    files.append(Path(__file__).with_name("native_source_head_diagnostics.py").resolve())
    return {str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest() for path in files}


def case(dsn, url, route, count, seconds, mode, timeline, diagnostics=None):
    fingerprint_started = monotonic()
    before = fingerprints()
    setup_started, setup_cpu = monotonic(), thread_time()
    with (
        native_environment(dsn, url) as (scratch, client, fanout),
        pytest.MonkeyPatch.context() as monkeypatch,
    ):
        owned = (scratch, client, fanout, url)
        factory_started, factory_cpu = monotonic(), thread_time()
        state = fixture(owned, monkeypatch, mode)
        state.admission_timings.append(
            {
                "kind": "setup",
                "fingerprint_seconds": setup_started - fingerprint_started,
                "environment_seconds": factory_started - setup_started,
                "environment_thread_cpu_seconds": factory_cpu - setup_cpu,
                "factory_seconds": monotonic() - factory_started,
                "factory_thread_cpu_seconds": thread_time() - factory_cpu,
            }
        )
        telemetry = Telemetry()
        telemetry.stage = f"http/{mode}/{route}/{count}"
        state.telemetry = telemetry
        try:
            with telemetry.installed(), _http_socket(state.app_factory()) as base:
                started = monotonic()
                results, renewals, window_seconds = asyncio.run(
                    observe(base, state, route, count, seconds, timeline)
                )
                elapsed = monotonic() - started
            after = fingerprints()
            assert before == after, "runtime/harness changed during measurement"
            assert not state.failures
            measured = telemetry.report()
            sql = sum(value for key, value in measured["calls"].items() if "/sql:" in key)
            subscriber_seconds = sum(item["seconds"] for item in results)
            starts = telemetry.sql_starts
            steady_sql = sum(
                state.steady_started <= stamp < state.steady_ended for stamp, _ in starts
            )
            startup_started_sql = sum(stamp < state.steady_started for stamp, _ in starts)
            shutdown_sql = sum(stamp >= state.steady_ended for stamp, _ in starts)
            steady_subscriber_seconds = (
                (state.steady_ended - state.steady_started) * count
                if timeline == "healthy"
                else None
            )
            startup_sql = sum(v for k, v in state.startup_calls.items() if "/sql:" in k)
            return {
                "route": route,
                "count": count,
                "mode": mode,
                "timeline": timeline,
                "seconds": elapsed,
                "subscriber_seconds": subscriber_seconds,
                "client_sql": sql,
                "startup_client_sql": startup_sql,
                "startup_calls": state.startup_calls,
                "window_and_reconnect_client_sql": sql - startup_sql,
                "sql_per_subscriber_second": sql / subscriber_seconds,
                "requested_seconds": seconds,
                "window_seconds": window_seconds,
                "all_subscribers_admitted": True,
                "steady_client_sql": steady_sql,
                "startup_sql_by_start": startup_started_sql,
                "postwindow_sql_by_start": shutdown_sql,
                "steady_subscriber_seconds": steady_subscriber_seconds,
                "steady_sql_per_subscriber_second": (
                    steady_sql / steady_subscriber_seconds
                    if steady_subscriber_seconds is not None
                    else None
                ),
                "slo_pass": seconds >= 600
                and timeline == "healthy"
                and state.steady_ended - state.steady_started >= 600
                and steady_sql / steady_subscriber_seconds <= 0.2,
                "steady_started": state.steady_started,
                "steady_ended": state.steady_ended,
                "sql_start_timestamps": starts,
                "fingerprints_start": before,
                "fingerprints_end": after,
                "lease_heartbeats": renewals,
                "subscribers": results,
                "telemetry": measured,
                "read_timings": state.read_timings,
                "admission_timings": state.admission_timings,
                "boundary": (
                    "real HTTP/auth/PG/Redis; startup and steady distinct; native Recorder/Turn; "
                    "actual checkpoint Consumer; one Run; no Worker/SDK"
                ),
            }
        except BaseException:
            if diagnostics is not None:
                diagnostics.update(failure_diagnostics(state, telemetry, seconds))
            raise
        finally:
            state.stopped.set()
            if state.thread is not None:
                state.thread.join(timeout=5)
                assert not state.thread.is_alive()
            if state.writer is not None:
                state.writer.close()
                state.writer._port._client.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=600)
    parser.add_argument("--sizes", default="1,10,100")
    parser.add_argument("--routes", default="session,task,agui")
    parser.add_argument("--modes", default="quiet,paused")
    parser.add_argument(
        "--timeline", choices=("healthy", "resume", "idle_resume"), default="idle_resume"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 900:
        raise ValueError("observation must be 1..900 seconds")
    sizes, routes, modes = (
        [int(n) for n in args.sizes.split(",")],
        args.routes.split(","),
        args.modes.split(","),
    )
    if (
        set(sizes) - {1, 10, 100}
        or set(routes) - {"session", "task", "agui"}
        or set(modes) - {"quiet", "paused"}
    ):
        raise ValueError("invalid source-head matrix")
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    dsn, url = (
        os.environ["ZEBRA_STREAM_TEST_POSTGRES_DSN"],
        os.environ["ZEBRA_STREAM_TEST_REDIS_URL"],
    )
    for mode in modes:
        for route in routes:
            for size in sizes:
                target = args.output / f"{args.timeline}-{mode}-{route}-{size}.json"
                if target.exists():
                    previous = json.loads(target.read_text())
                    if previous["requested_seconds"] != args.seconds:
                        raise ValueError("resume requires same complete observation window")
                    if previous["fingerprints_end"] != fingerprints():
                        raise ValueError("resume requires unchanged runtime/harness")
                    continue
                start = target.with_suffix(".start.json")
                start.write_text(
                    json.dumps(
                        {
                            "fingerprints": fingerprints(),
                            "requested_seconds": args.seconds,
                            "timeline": args.timeline,
                        }
                    )
                    + "\n"
                )
                start.chmod(0o600)
                diagnostics = {}
                try:
                    result = case(
                        dsn, url, route, size, args.seconds, mode, args.timeline, diagnostics
                    )
                except BaseException as exc:
                    error = target.with_suffix(".error.json")
                    error.write_text(
                        json.dumps(
                            {
                                "error_type": type(exc).__name__,
                                "fingerprints_end": fingerprints(),
                                **diagnostics,
                            }
                        )
                        + "\n"
                    )
                    error.chmod(0o600)
                    raise
                target.write_text(json.dumps(result, indent=2) + "\n")
                target.chmod(0o600)
                print(
                    json.dumps(
                        {
                            key: result[key]
                            for key in (
                                "mode",
                                "route",
                                "count",
                                "client_sql",
                                "subscriber_seconds",
                                "sql_per_subscriber_second",
                                "slo_pass",
                            )
                        }
                    ),
                    flush=True,
                )


if __name__ == "__main__":
    main()
