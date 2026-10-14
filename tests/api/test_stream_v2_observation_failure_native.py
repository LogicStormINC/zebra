"""Canonical dependency faults reset drafts and close without a canonical Task failure."""

import asyncio
import json
import os
import sys
from time import monotonic

import psycopg
import pytest
from agent_storage.postgres.task_io import TaskIoConnection
from zebra_agent_api.stream_v2_wire import stream_notice

from tests.api.test_stream_v2_native import Request, opened
from tests.stream_storage import native_source_head_http as harness
from tests.stream_storage.telemetry import LABEL
from tests.worker.test_transient_output_composition_native import owned as _owned_fixture

owned = _owned_fixture


@pytest.mark.parametrize("route", ["session", "task", "agui"])
@pytest.mark.parametrize("error_type", [TimeoutError, psycopg.OperationalError])
def test_native_canonical_dependency_fault_resets_before_retryable_close(
    owned, monkeypatch, route, error_type
):
    _, writer, _, reader, bound, _ = opened(owned, monkeypatch, frames=1)
    context = reader.context(bound, kind=route, token=None, full_recovery=True)
    closed = []

    async def source():
        try:
            yield stream_notice("zebra.stream.recovery_complete", {})
            raise error_type()
        finally:
            closed.append(True)

    async def collect():
        try:
            return [
                frame
                async for frame in reader.tail(
                    context,
                    source(),
                    deadline=monotonic() + 5,
                    disconnected=Request().is_disconnected,
                )
            ]
        finally:
            await reader.close()

    try:
        frames = asyncio.run(collect())
        assert '"canonical_unavailable"' in frames[-2]
        assert '"zebra.observation.problem"' in frames[-1]
        assert '"observation_unavailable"' in frames[-1] and '"retryable":true' in frames[-1]
        assert closed == [True] and not any('"zebra.stream.draft"' in f for f in frames[-2:])
    finally:
        writer.close()


def test_native_unknown_cancel_and_authority_boundary_are_preserved(owned, monkeypatch):
    from zebra_agent_api import stream_v2_reader

    _, writer, _, reader, bound, _ = opened(owned, monkeypatch, frames=1)
    context = reader.context(bound, kind="session", token=None, full_recovery=True)

    async def check(error, boundary=None, boundary_patch=None):
        async def source():
            yield stream_notice("zebra.stream.recovery_complete", {})
            raise error

        disconnected = False

        async def gone():
            return disconnected

        deadline = monotonic() + 5
        stream = reader.tail(context, source(), deadline=deadline, disconnected=gone)
        frames = []
        try:
            async for frame in stream:
                frames.append(frame)
                if '"canonical_unavailable"' in frame:
                    if boundary == "disconnect":
                        disconnected = True
                    elif boundary == "deadline":
                        boundary_patch.setattr(stream_v2_reader, "monotonic", lambda: deadline + 1)
            return frames
        finally:
            await stream.aclose()

    async def all_checks():
        try:
            for error in (ValueError(), asyncio.CancelledError()):
                with pytest.raises(type(error)) as raised:
                    await check(error)
                assert raised.value is error
            for boundary in ("disconnect", "deadline"):
                with monkeypatch.context() as patch:
                    frames = await check(TimeoutError(), boundary, patch)
                assert '"canonical_unavailable"' in frames[-1]
                assert not any('"zebra.observation.problem"' in frame for frame in frames)
        finally:
            await reader.close()

    try:
        asyncio.run(all_checks())
    finally:
        writer.close()


def test_actual_http_canonical_connect_fault_is_graceful_but_fails_healthy_600(
    monkeypatch, record_property
):
    dsn, url = (
        os.environ.get("ZEBRA_STREAM_TEST_POSTGRES_DSN"),
        os.environ.get("ZEBRA_STREAM_TEST_REDIS_URL"),
    )
    if not dsn or not url:
        pytest.skip("owned native PostgreSQL and Redis are required")
    original_fixture, original_capture = harness.fixture, harness.capture_asgi_exception
    captured, complete_names = {}, []

    async def capture(app, scope, receive, send, records, lock):
        async def watch(message):
            # Each ASGI body is an existing complete encoder record; retain only names.
            body = message.get("body", b"").decode()
            for record in body.split("\n\n")[:-1]:
                for line in record.splitlines():
                    if line.startswith("data: "):
                        event = json.loads(line[6:])
                        if event.get("name"):
                            complete_names.append(event["name"])
            await send(message)

        await original_capture(app, scope, receive, watch, records, lock)

    def fixture(owned, patch, mode):
        state = original_fixture(owned, patch, mode)
        captured["state"] = state
        original, injected = TaskIoConnection._connect_gen, False

        def connect(cls, *args, **kwargs):
            nonlocal injected
            frame, canonical = sys._getframe(), False
            while frame:
                canonical |= frame.f_code.co_name == "read_stream_source_head"
                frame = frame.f_back
            if (
                not injected
                and canonical
                and LABEL.get() == "http/initial/0/taskio-connect"
                and getattr(state, "recovered", [False])[0]
            ):
                injected = True
                captured["injected"] = monotonic()
                raise TimeoutError()
            return (yield from original(*args, **kwargs))

        patch.setattr(TaskIoConnection, "_connect_gen", classmethod(connect))
        return state

    monkeypatch.setattr(harness, "fixture", fixture)
    monkeypatch.setattr(harness, "capture_asgi_exception", capture)
    diagnostics = {}
    with pytest.raises(AssertionError, match="HTTP stream closed before observation deadline"):
        harness.case(dsn, url, "session", 1, 600, "paused", "healthy", diagnostics)
    assert "injected" in captured and diagnostics["recovered"] == 1
    assert complete_names[-2:] == ["zebra.stream.reset", "zebra.observation.problem"]
    assert not any(r["kind"] == "asgi-exception" for r in diagnostics["admission_timings"])
    assert not diagnostics["slo_pass"] and not diagnostics["completed_steady_window"]
    assert diagnostics["steady_ended"] is None and diagnostics["observed_steady_seconds"] < 600
    record_property("observed_steady_seconds", diagnostics["observed_steady_seconds"])
    record_property("completed_lease_heartbeats", diagnostics["lease_heartbeats"])
