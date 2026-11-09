"""Offer work at fixed deadlines and preserve generator saturation in the record."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from math import isfinite


@dataclass
class Offer:
    index: int
    scheduled: float
    issued: float | None = None
    finished: float | None = None
    disposition: str = "pending"


async def run_offers(
    submit: Callable[[int], Awaitable[str]],
    *,
    rate: float,
    duration: float,
    max_inflight: int,
    request_timeout: float,
) -> list[Offer]:
    if (
        any(not isfinite(value) or value <= 0 for value in (rate, duration, request_timeout))
        or not 1 <= max_inflight <= 16
    ):
        raise ValueError("invalid E1 offer window")
    slots = rate * duration
    if not 1 <= slots <= 36_000 or slots != int(slots):
        raise ValueError("E1 window requires an integral bounded offer count")
    loop = asyncio.get_running_loop()
    start = loop.time()
    interval = 1 / rate
    offers = [Offer(index, index * interval) for index in range(int(slots))]
    active: set[asyncio.Task[None]] = set()

    async def issue(offer: Offer) -> None:
        offer.issued = loop.time() - start
        try:
            async with asyncio.timeout(request_timeout):
                offer.disposition = await submit(offer.index)
        except TimeoutError:
            offer.disposition = "request_timeout"
        except Exception as exc:
            offer.disposition = f"request_error:{type(exc).__name__}"
        finally:
            offer.finished = loop.time() - start

    async with asyncio.TaskGroup() as group:
        for offer in offers:
            await asyncio.sleep(max(0, start + offer.scheduled - loop.time()))
            active = {task for task in active if not task.done()}
            if loop.time() - start >= offer.scheduled + interval:
                offer.disposition = "generator_late"
            elif len(active) >= max_inflight:
                offer.disposition = "generator_saturated"
            else:
                active.add(group.create_task(issue(offer)))
    return offers


async def _check() -> None:
    submitted = []
    release = asyncio.Event()

    async def submit(index: int) -> str:
        submitted.append(index)
        await release.wait()
        return "completed"

    blocked = asyncio.create_task(
        run_offers(submit, rate=20.0, duration=0.2, max_inflight=1, request_timeout=1)
    )
    await asyncio.sleep(0.25)
    release.set()
    offers = await blocked
    assert len(offers) == 4 and submitted == [0]
    assert offers[0].disposition == "completed"
    assert all(offer.disposition == "generator_saturated" for offer in offers[1:])
    assert all(offer.issued is None for offer in offers[1:])


if __name__ == "__main__":
    asyncio.run(_check())
