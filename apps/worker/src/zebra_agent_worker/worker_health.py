"""Private process observations, refreshed by real Worker progress only."""

import json
import logging
import os
import stat
import tempfile
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Any, cast
from uuid import uuid4

logger = logging.getLogger(__name__)


class WorkerHealth:
    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        self._clock, self._lock = clock, RLock()
        self._instance = str(uuid4())
        self._phase = "starting"
        self._at: float | None = None
        self._ready = False
        self._control_at: float | None = None
        self._valid_until = 0.0
        self._path: Path | None = None
        self._write_failed = False

    def attach(self, path: Path) -> None:
        if not path.is_absolute():
            raise ValueError("Worker health file must be an absolute operator-owned path")
        with self._lock:
            if self._path is not None or self._phase == "stopped":
                raise RuntimeError("Worker observation lifecycle already attached or closed")
            # ponytail: manager supplies a fresh path; stable-path takeover needs
            # an owner-fenced protocol. Never overwrite existing data on attach.
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(descriptor, "w") as stream:
                    json.dump(self.snapshot(), stream)
            except BaseException:
                with suppress(OSError):
                    path.unlink()
                raise
            self._path = path

    def _record(
        self,
        phase: str,
        ready: bool,
        *,
        valid_until: float | None = None,
        progress_at: float | None = None,
    ) -> None:
        with self._lock:
            if self._phase == "stopped":
                return
            self._phase, self._ready, self._at = phase, ready, self._clock()
            self._control_at = self._at if progress_at is None else progress_at
            self._valid_until = min(
                self._at + 5, self._at + 5 if valid_until is None else valid_until
            )
            self._publish()

    def legacy_tick(self, *, busy: bool) -> None:
        # A serial long call has no independent control tick: do not invent one.
        self._record("legacy_busy" if busy else "legacy_idle", not busy)

    def command_tick(self, lease: Any, work_completed_at: float) -> None:
        now = self._clock()
        current = (
            lease is not None
            and lease.expires_at > datetime.now(UTC)
            and 0 < work_completed_at <= now
            and now - work_completed_at <= 5
        )
        remaining = 0 if lease is None else (lease.expires_at - datetime.now(UTC)).total_seconds()
        self._record(
            "command",
            current,
            valid_until=min(now + remaining, work_completed_at + 5),
            progress_at=work_completed_at,
        )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            fresh = self._at is not None and 0 <= self._clock() - self._at <= 5
            control_fresh = (
                self._control_at is not None and 0 <= self._clock() - self._control_at <= 5
            )
            return {
                "pid": os.getpid(),
                "instance_id": self._instance,
                "phase": self._phase,
                "observed_at": self._at,
                "control_observed_at": self._control_at,
                "ready": (
                    self._ready
                    and fresh
                    and self._clock() <= self._valid_until
                    and not self._write_failed
                ),
                "valid_until": self._valid_until,
                "control_fresh": control_fresh and self._phase not in {"legacy_busy", "stopped"},
            }

    def close(self) -> None:
        with self._lock:
            if self._phase == "stopped":
                return
            self._phase, self._ready = "stopped", False
            self._publish()

    def _publish(self) -> None:
        if self._path is None:
            return
        temporary: str | None = None
        previous_failure = self._write_failed
        try:
            # ponytail: one small atomic file in a trusted operator directory, no daemon/port.
            # A distributed observer must use Runtime gates instead of this local snapshot.
            self._write_failed = False
            with tempfile.NamedTemporaryFile(
                mode="w", dir=self._path.parent, delete=False
            ) as stream:
                temporary = stream.name
                json.dump(self.snapshot(), stream)
            os.replace(temporary, self._path)
        except OSError:
            if not previous_failure:
                logger.warning("worker_health_snapshot_unavailable")
            self._write_failed = True
        finally:
            if temporary is not None:
                with suppress(OSError):
                    Path(temporary).unlink(missing_ok=True)


def read_worker_health(path: Path, pid: int, instance_id: str, *, now: float) -> dict[str, Any]:
    """Caller pins the expected process identity; file contents cannot grant execution."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(descriptor) as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return {"ready": False, "control_fresh": False, "phase": "unknown"}
            raw = stream.read(4097)
        if len(raw) > 4096:
            return {"ready": False, "control_fresh": False, "phase": "unknown"}
        state = json.loads(raw)
        at = state.get("observed_at")
        until = state.get("valid_until")
        valid = (
            isinstance(state, dict)
            and state.get("pid") == pid
            and state.get("instance_id") == instance_id
            and type(at) in (int, float)
            and type(until) in (int, float)
            and isfinite(until)
            and now <= until
            and isfinite(at)
            and isfinite(now)
            and type(state.get("ready")) is bool
            and 0 <= now - at <= 5
            and state.get("phase") != "stopped"
        )
        if valid:
            return cast(dict[str, Any], state)
    except (OSError, ValueError, AttributeError):
        pass
    return {"ready": False, "control_fresh": False, "phase": "unknown"}
