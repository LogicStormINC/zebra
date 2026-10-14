"""Owned canonical hint publisher with one bounded maintenance budget."""

from threading import Condition
from time import monotonic
from uuid import uuid4

from agent_integrations.redis_live_fanout import RedisLiveEventFanout
from agent_integrations.redis_transient_deadlines import (
    current_redis_io_deadline,
    redis_io_deadline,
)
from agent_storage.postgres.stream_hint_relay import claim_stream_hints, settle_stream_hint
from agent_storage.postgres.task_io import current_task_io_deadline, task_io_deadline
from psycopg import Error as PostgresError
from redis.exceptions import RedisError


class StreamHintRelay:
    def __init__(self, dsn: str, namespace: str, publisher: RedisLiveEventFanout) -> None:
        self.dsn, self.namespace, self.publisher = dsn, namespace, publisher
        self.owner = str(uuid4())
        self._state = Condition()
        self._active = self._closed = self._disposed = False

    def tick(self) -> int:
        with self._state:
            if self._closed or self._active:
                return 0
            self._active = True
        deadline = min(
            monotonic() + 2,
            current_task_io_deadline() or float("inf"),
            current_redis_io_deadline() or float("inf"),
        )
        published = 0
        try:
            with task_io_deadline(deadline), redis_io_deadline(deadline):
                claims = claim_stream_hints(self.dsn, namespace=self.namespace, owner=self.owner)
                for claim in claims:
                    # ponytail: unstarted items retain reclaimable leases; batching is capped32.
                    if monotonic() + 0.02 >= deadline:
                        break
                    confirmed = False
                    try:
                        self.publisher.publish_frontier(
                            deployment_namespace=claim.namespace,
                            session_id=claim.session_id,
                            through=claim.through,
                        )
                        confirmed = True
                    except (RedisError, TimeoutError):
                        pass
                    if monotonic() + 0.02 >= deadline:
                        break  # No fresh settlement budget: lease recovery owns this uncertainty.
                    published += int(
                        settle_stream_hint(self.dsn, claim, confirmed=confirmed) and confirmed
                    )
        except (PostgresError, RedisError, TimeoutError):
            pass  # Expected hint transport failure must not back off unrelated recovery.
        finally:
            with self._state:
                self._active = False
                if self._closed:
                    self._dispose()
                self._state.notify_all()
        return published

    def _dispose(self) -> None:
        if not self._disposed:
            self._disposed = True
            self.publisher.close()

    def close(self) -> None:
        with self._state:
            self._closed = True
            self._state.wait_for(lambda: not self._active, timeout=2)
            if not self._active:
                self._dispose()
            # An over-budget tick disposes on exit; never close its checked-out socket here.
