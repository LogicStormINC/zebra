"""Call-owned numeric MCP spans; parent and child spans intentionally overlap."""

from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter


@contextmanager
def mcp_phase(timings: dict[str, float] | None, name: str) -> Iterator[None]:
    if timings is None:
        yield
        return
    started = perf_counter()
    try:
        yield
    finally:
        timings[name] = timings.get(name, 0.0) + (perf_counter() - started) * 1000
