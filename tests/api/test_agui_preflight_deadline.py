"""Grant-bounded preflight preserves synchronous Ports without blocking the loop."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from time import monotonic

import pytest
from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointNotReady
from zebra_agent_api import ag_ui_task_view
from zebra_agent_api.ag_ui_task_view import authorized_task_preflight
from zebra_agent_api.responses import ApiResponse


def test_expired_grant_never_calls_authorization_or_preflight() -> None:
    def forbidden() -> None:
        raise AssertionError("expired request started work")

    response = asyncio.run(
        authorized_task_preflight(
            forbidden, forbidden, authorization_expires_at=datetime.now(UTC) - timedelta(seconds=1)
        )
    )
    assert isinstance(response, ApiResponse) and response.status_code == 403


def test_denied_access_preserves_response_without_preflight() -> None:
    denied = ApiResponse(404, {"status": "not_found"})

    def forbidden() -> None:
        raise AssertionError("denied request prepared SSE")

    result = asyncio.run(
        authorized_task_preflight(lambda: denied, forbidden, authorization_expires_at=None)
    )
    assert result is denied


def test_expired_inherited_request_deadline_starts_no_reads() -> None:
    calls: list[str] = []
    result = asyncio.run(
        authorized_task_preflight(
            lambda: calls.append("authorize"),
            lambda: calls.append("prepare"),
            authorization_expires_at=None,
            request_deadline=monotonic() - 1,
        )
    )
    assert isinstance(result, ApiResponse) and result.status_code == 503
    assert calls == []


def test_preflight_keeps_the_remaining_request_io_budget() -> None:
    from agent_storage.postgres.task_io import _TASK_IO_DEADLINE

    deadline = monotonic() + 1
    observed: list[float | None] = []
    result = asyncio.run(
        authorized_task_preflight(
            lambda: observed.append(_TASK_IO_DEADLINE.get()),
            lambda: observed.append(_TASK_IO_DEADLINE.get()),
            authorization_expires_at=None,
            request_deadline=deadline,
        )
    )
    assert result is None
    assert observed == [deadline, deadline]


@pytest.mark.parametrize("error,status", [(CheckpointNotReady, 409), (CheckpointConflict, 409)])
def test_preflight_distinguishes_not_ready_and_conflict(
    error: type[Exception], status: int
) -> None:
    def prepare() -> None:
        raise error("source metadata")

    result = asyncio.run(
        authorized_task_preflight(lambda: None, prepare, authorization_expires_at=None)
    )
    assert isinstance(result, ApiResponse) and result.status_code == status
    assert result.body["retryable"] is (error is CheckpointNotReady)


def test_auth_and_preflight_leave_the_event_loop_responsive() -> None:
    started, release, ticks = Event(), Event(), []

    def prepare() -> str:
        started.set()
        assert release.wait(1), "preflight blocked the event loop"
        return "prepared"

    async def run() -> str | ApiResponse:
        task = asyncio.create_task(
            authorized_task_preflight(lambda: None, prepare, authorization_expires_at=None)
        )
        try:
            async with asyncio.timeout(1):
                while not started.is_set():
                    await asyncio.sleep(0)
                ticks.append(True)
        finally:
            release.set()
        return await task

    assert asyncio.run(run()) == "prepared" and ticks == [True]


def test_queued_expiry_starts_no_reads_or_late_sse() -> None:
    occupied, release = Event(), Event()
    calls: list[str] = []

    def holder() -> None:
        occupied.set()
        release.wait(1)

    async def run() -> ApiResponse | None:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            loop.set_default_executor(pool)
            holding = asyncio.create_task(asyncio.to_thread(holder))
            while not occupied.is_set():
                await asyncio.sleep(0)
            try:
                result = await authorized_task_preflight(
                    lambda: calls.append("authorize"),
                    lambda: calls.append("prepare"),
                    authorization_expires_at=datetime.now(UTC) + timedelta(milliseconds=30),
                )
            finally:
                release.set()
                await holding
        return result

    result = asyncio.run(run())
    assert isinstance(result, ApiResponse) and result.status_code == 403
    assert calls == []


def test_expiry_between_reads_cannot_start_preflight() -> None:
    release, finished, calls = Event(), Event(), []

    def authorize() -> None:
        try:
            assert release.wait(1)
        finally:
            finished.set()

    async def run() -> ApiResponse | None:
        try:
            return await authorized_task_preflight(
                authorize,
                lambda: calls.append("prepare"),
                authorization_expires_at=datetime.now(UTC) + timedelta(milliseconds=30),
            )
        finally:
            release.set()
            async with asyncio.timeout(1):
                while not finished.is_set():
                    await asyncio.sleep(0)

    result = asyncio.run(run())
    assert isinstance(result, ApiResponse) and result.status_code == 403
    assert calls == []


@pytest.mark.parametrize("stage", ["authorize", "prepare"])
@pytest.mark.parametrize("error", [None, CheckpointNotReady, CheckpointConflict])
def test_wall_clock_expiry_rejects_success_and_projection_errors(
    stage: str, error: type[Exception] | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = datetime.now(UTC)
    expires = current + timedelta(hours=1)
    calls: list[str] = []

    class Clock:
        @staticmethod
        def now(zone: object) -> datetime:
            return current

    def expire(name: str) -> None:
        nonlocal current
        calls.append(name)
        if stage == name:
            current = expires + timedelta(seconds=1)
            if error is not None:
                raise error("late projection result")

    def prepare() -> str:
        expire("prepare")
        return "prepared-after-expiry"

    monkeypatch.setattr(ag_ui_task_view, "datetime", Clock)
    result = asyncio.run(
        authorized_task_preflight(
            lambda: expire("authorize"), prepare, authorization_expires_at=expires
        )
    )
    assert isinstance(result, ApiResponse) and result.status_code == 403
    assert calls == (["authorize"] if stage == "authorize" else ["authorize", "prepare"])


@pytest.mark.parametrize("stage", ["before", "read", "consumer"])
def test_stream_checks_wall_clock_before_reads_and_after_backpressure(
    stage: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = datetime.now(UTC)
    expires = current + timedelta(hours=1)
    reads, closed = [], []

    class Clock:
        @staticmethod
        def now(zone: object) -> datetime:
            return current

    async def source() -> AsyncGenerator[str, None]:
        nonlocal current
        try:
            reads.append(True)
            if stage == "read":
                current = expires
            yield "first"
            reads.append(True)
            yield "late"
        finally:
            closed.append(True)

    async def run() -> list[str]:
        nonlocal current
        result = []
        if stage == "before":
            current = expires
        async for frame in ag_ui_task_view.deadline_frames(
            source(), monotonic() + 1, authorization_expires_at=expires
        ):
            result.append(frame)
            current = expires
        return result

    monkeypatch.setattr(ag_ui_task_view, "datetime", Clock)
    assert asyncio.run(run()) == (["first"] if stage == "consumer" else [])
    assert reads == ([] if stage == "before" else [True])
    assert closed == ([] if stage == "before" else [True])
