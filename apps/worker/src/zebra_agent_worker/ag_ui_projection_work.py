"""Process-owned checkpoint consumer; never an execution or observation Agent."""

import logging
from threading import Event, Lock, Thread
from time import monotonic

from agent_integrations.ag_ui.checkpoint_consumer import AgUiCheckpointConsumer
from agent_storage.postgres.connection_pool import postgres_context

logger = logging.getLogger(__name__)


class AgUiProjectionWorkService:
    def __init__(
        self,
        consumer: AgUiCheckpointConsumer,
        *,
        interval_seconds: float = 0.1,
        coverage_consumer: AgUiCheckpointConsumer | None = None,
        additional_consumers: tuple[AgUiCheckpointConsumer, ...] = (),
    ) -> None:
        if not 0.01 <= interval_seconds <= 2:
            raise ValueError("invalid projection polling interval")
        self.consumer, self.interval = consumer, interval_seconds
        self.consumers = (
            (consumer,) if coverage_consumer is None else (consumer, coverage_consumer)
        ) + additional_consumers
        self._stop, self._lock = Event(), Lock()
        self._thread: Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = Thread(
                target=postgres_context().run, args=(self._run,),
                name="ag-ui-projection", daemon=True,
            )
            self._thread.start()

    def _run(self) -> None:
        enabled: set[int] = set()
        # E1-A idle-cost fix: a completed bootstrap re-locks the projector config
        # row FOR UPDATE on every call; re-check it at a bounded cadence instead.
        bootstrap_done_until: dict[int, float] = {}
        bootstrap_recheck_seconds = 60.0
        # E1-A idle-cost fix: 10 Hz polling with no pending work is ~300 idle
        # transactions/s per fleet against PG; stretch the interval when idle
        # and reset to the base interval on any progress.
        delay = self.interval
        idle_cap = 1.0
        while not self._stop.is_set():
            progressed = False
            for index, consumer in enumerate(self.consumers):
                try:
                    if index not in enabled:
                        consumer.work.enable_projection_work()
                        enabled.add(index)
                    now = monotonic()
                    if bootstrap_done_until.get(index, 0.0) <= now:
                        if consumer.work.bootstrap_projection_work(limit=32):
                            bootstrap_done_until[index] = now + bootstrap_recheck_seconds
                        else:
                            progressed = True  # bootstrap still chewing through batches
                    if consumer.poll_once():
                        progressed = True
                except Exception as exc:
                    logger.warning("AG-UI projection maintenance failed: %s", type(exc).__name__)
                    delay = max(delay, 1.0)
            if progressed:
                delay = self.interval
            else:
                delay = min(delay * 2, idle_cap)
            self._stop.wait(delay)

    def close(self) -> None:
        with self._lock:
            self._stop.set()
            if self._thread is not None:
                self._thread.join(timeout=5)
                if self._thread.is_alive():
                    # Cleanup must not mask an execution failure or cancellation.
                    logger.error("AG-UI projection consumer did not drain within its I/O budget")
