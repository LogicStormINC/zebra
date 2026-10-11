"""Bounded read-only runtime checks; never retry container side effects."""

from subprocess import TimeoutExpired
from time import sleep

from agent_core.ports.runtime import RuntimeCapabilities, RuntimeCapabilityError, RuntimePort


def require_runtime_capabilities(runtime: RuntimePort) -> RuntimeCapabilities:
    for attempt in range(3):
        try:
            capabilities = runtime.inspect_capabilities()
        except (TimeoutExpired, TimeoutError, ConnectionError):
            if attempt == 2:
                raise RuntimeCapabilityError("OCI engine capability check timed out") from None
            sleep(0.2 * (attempt + 1))
            continue
        if capabilities.available:
            return capabilities
        if not capabilities.retryable or attempt == 2:
            raise RuntimeCapabilityError(capabilities.reason or "hard runtime is unavailable")
        sleep(0.2 * (attempt + 1))
    raise AssertionError("bounded runtime capability check exhausted")
