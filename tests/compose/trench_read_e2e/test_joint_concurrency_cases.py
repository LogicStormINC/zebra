"""Concurrency evidence guards; fabricated parser samples are NOT live acceptance."""

import asyncio
import time
from copy import deepcopy

import httpx
import pytest
from joint_concurrency_cases import (
    FrameCapture,
    _observe,
    validate_concurrency,
    validate_dimensions,
)
from support import E2EError


def evidence(count=10):
    rows = []
    for index in range(count):
        slow = count > 1 and index == count - 1
        rows.append(
            {
                "observer": index,
                "slow": slow,
                "opened": True,
                "final_receipt_ms": 120 if slow else 99,
                "body_bytes": 123,
                "frames": [{"cursor": 8, "answer_committed": True, "payload_sha256": "same"}],
            }
        )
    return {
        "history_floor": 1000,
        "observer_count": count,
        "observers": rows,
        "history": {"actual_session_events": 1000, "canonical_final_writes": 0},
        "all_headers_before_terminal": True,
        "provider_substitution": False,
        "healthy_final_ms": 100,
        "cleanup": {"status": "passed"},
        "cleanup_after_final_ms": 500,
    }


@pytest.mark.parametrize("count", [1, 10, 50, 100])
def test_complete_dimension_requires_each_observer_and_slow_read_gate(count):
    value = evidence(count)
    validate_concurrency(value)
    value["observers"].pop()
    with pytest.raises(E2EError):
        validate_concurrency(value)


@pytest.mark.parametrize("history", [1000, 10000, 100000])
@pytest.mark.parametrize("count", [1, 10, 50, 100])
def test_exact_matrix_dimensions(history, count):
    validate_dimensions(history, count)


@pytest.mark.parametrize(
    "field,value",
    [
        ("all_headers_before_terminal", False),
        ("provider_substitution", True),
        ("cleanup_after_final_ms", 5001),
        ("cleanup_after_final_ms", -1),
    ],
)
def test_no_false_concurrency_pass(field, value):
    data = evidence()
    data[field] = value
    with pytest.raises(E2EError):
        validate_concurrency(data)


def test_no_history_or_cleanup_guess_and_same_final_for_every_client():
    base = evidence()
    variations = []
    for change in ("history", "cleanup", "slow", "final", "duplicate"):
        data = deepcopy(base)
        if change == "history":
            data["history"]["actual_session_events"] = 999
        elif change == "cleanup":
            data["cleanup"]["status"] = "pending"
        elif change == "slow":
            data["observers"][-1]["final_receipt_ms"] = 99
        elif change == "final":
            data["observers"][0]["frames"][0]["payload_sha256"] = "different"
        else:
            data["observers"][0]["frames"] *= 2
        variations.append(data)
    for data in variations:
        with pytest.raises(E2EError):
            validate_concurrency(data)


def test_existing_decoder_hashes_private_body_without_retaining_it():
    capture = FrameCapture()
    for line in ("id: 1", 'data: {"answer_committed":true,"private":"NEVER_EXPORT"}', ""):
        frame = capture.feed(line)
    assert frame["answer_committed"] is True
    assert "NEVER_EXPORT" not in str(capture.frames)
    capture.finish()
    for line in ("id: 1", "data: {}"):
        capture.feed(line)
    with pytest.raises(E2EError, match="cursor"):
        capture.feed("")


def test_diagnostic_and_incomplete_stream_never_prove_final():
    capture = FrameCapture()
    capture.feed('data: {"retryable":true}')
    with pytest.raises(E2EError, match="unpositioned"):
        capture.feed("")
    capture = FrameCapture()
    capture.feed("id: 2")
    with pytest.raises(E2EError, match="truncated"):
        capture.finish()
    with pytest.raises(E2EError, match="byte_limit"):
        capture.feed("data: " + "x" * 65536)


def test_short_final_is_observed_before_transport_eof():
    """Transport guard only: fixed HTTPX chunk sizes must not delay short SSE frames."""

    class ShortStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b'id: 1\ndata: {"answer_committed":true}\n\n'
            raise AssertionError("final consumer requested EOF instead of returning immediately")

        async def aclose(self):
            self.closed = True

    async def check():
        stream = ShortStream()
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=stream
            )
        )
        gate = asyncio.Event()
        gate.set()
        opened = asyncio.Queue()
        async with httpx.AsyncClient(transport=transport) as client:
            row = await _observe(
                client,
                "https://transport.invalid/events",
                0,
                slow=False,
                opened=opened,
                read_gate=gate,
                fast_done=asyncio.Event(),
                started=time.monotonic(),
            )
        assert stream.closed and opened.get_nowait() == 0
        assert row["frames"][0]["answer_committed"] is True
        assert row["body_bytes"] < 4096

    asyncio.run(check())
