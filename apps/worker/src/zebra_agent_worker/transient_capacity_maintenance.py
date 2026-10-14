"""One bounded Worker-owned retained-draft collector, never reader maintenance."""

from threading import Lock
from time import monotonic

from agent_integrations.redis_transient_deadlines import (
    current_redis_io_deadline,
    redis_io_deadline,
)
from agent_integrations.redis_transient_output import (
    RedisTransientOutput,
    TransientOutputUnavailable,
)
from agent_storage.postgres.task_io import current_task_io_deadline, task_io_deadline
from redis.exceptions import RedisError
from zebra_agent_config import ZebraAgentSettings


class TransientCapacityMaintenance:
    def __init__(self, port: RedisTransientOutput, namespace: str, settings: ZebraAgentSettings):
        self._port, self._namespace = port, namespace
        self._policy = settings.stream.capacity_policy
        self._lock = Lock()
        self._closing = False
        self._closed = False
        self._next = 0.0

    def tick(self) -> int:
        if self._closing or monotonic() < self._next or not self._lock.acquire(blocking=False):
            return 0
        try:
            if self._closing or monotonic() < self._next:
                return 0
            self._next = monotonic() + 1
            deadline = min(x for x in (monotonic() + 2, current_task_io_deadline(),
                                     current_redis_io_deadline()) if x is not None)
            with task_io_deadline(deadline), redis_io_deadline(deadline):
                assert self._policy is not None
                return self._port.collect_namespace_capacity(self._namespace, self._policy)
        except (RedisError, OSError, TimeoutError, TransientOutputUnavailable):
            return 0  # Conservative charges survive expected outages; fixed local cadence.
        finally:
            if self._closing and not self._closed:
                self._port.close()
                self._closed = True
            self._lock.release()

    def close(self) -> None:
        self._closing = True
        if self._lock.acquire(timeout=2):
            try:
                if not self._closed:
                    self._port.close()
                    self._closed = True
            finally:
                self._lock.release()
        # An active bounded tick closes its owned client on exit; no concurrent disconnect.


def configure_transient_capacity_maintenance(
    namespace: str | None, settings: ZebraAgentSettings,
) -> TransientCapacityMaintenance | None:
    if (settings.deployment != "cloud" or settings.stream.capacity_policy is None or
            not namespace or not settings.live_events.redis_url):
        return None
    port = RedisTransientOutput.from_url(
        settings.live_events.redis_url,
        resolve_authorization=lambda _: (_ for _ in ()).throw(
            TransientOutputUnavailable("maintenance cannot authorize publication")
        ),
    )
    return TransientCapacityMaintenance(port, namespace, settings)
