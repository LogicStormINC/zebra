from __future__ import annotations

import threading
from collections.abc import Callable


class Mem0CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int,
        recovery_seconds: float,
        clock: Callable[[], float],
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_seconds = recovery_seconds
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open_probe = False
        self._lock = threading.Lock()

    def allows_request(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return True
            if self._clock() - self._opened_at < self._recovery_seconds:
                return False
            if self._half_open_probe:
                return False
            # ponytail: one process-local breaker is enough for the first adapter;
            # a distributed admission gate belongs with multi-Worker operations.
            self._half_open_probe = True
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._half_open_probe = False

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._failure_threshold:
                self._opened_at = self._clock()
                self._half_open_probe = False
