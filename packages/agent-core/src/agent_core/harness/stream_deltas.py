"""Bound provider text chunks before they enter the durable Event stream."""

from collections.abc import Callable
from threading import RLock, Timer
from time import monotonic

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.modeling import ModelTextDelta
from agent_core.harness.models import HarnessEventDraft

MAX_DELTA_BUFFER_CHARACTERS = 65_536


class TextDeltaCoalescer:
    """Emit the first chunk immediately, then bounded character/time batches."""

    def __init__(
        self,
        sink: Callable[[HarnessEventDraft], None],
        *,
        attempt_number: int,
        characters: int | None,
        seconds: float | None,
    ) -> None:
        if characters is not None and characters <= 0:
            raise ValueError("delta_coalesce_characters must be positive")
        if seconds is not None and seconds <= 0:
            raise ValueError("delta_coalesce_seconds must be positive")
        self._sink = sink
        self._attempt_number = attempt_number
        self._characters = characters
        self._seconds = seconds
        self._lock = RLock()
        self._timer: Timer | None = None
        self._timer_error: Exception | None = None
        self._timer_generation = 0
        self.reset()

    def reset(self, model_call_id: str | None = None) -> None:
        with self._lock:
            self._cancel_timer()
            self._reset_buffer()
            self._first_emitted = False
            self._generation_call = model_call_id

    def _reset_buffer(self) -> None:
        self._call_id: str | None = None
        self._index = 0
        self._content = ""
        self._started_at: float | None = None

    def emit(self, model_call_id: str, delta: ModelTextDelta) -> None:
        with self._lock:
            self._raise_timer_error()
            if self._generation_call is not None and model_call_id != self._generation_call:
                return  # A retired provider callback cannot enter the next invocation.
            self._emit_locked(model_call_id, delta)

    def _emit_locked(self, model_call_id: str, delta: ModelTextDelta) -> None:
        if len(delta.content) > MAX_DELTA_BUFFER_CHARACTERS:
            raise ValueError("provider text delta exceeds buffer limit")
        if (self._characters is None and self._seconds is None) or not self._first_emitted:
            self._emit_event(model_call_id, delta.index, delta.content)
            self._first_emitted = True
            return
        if not self._content:
            self._call_id = model_call_id
            self._index = delta.index
            self._started_at = monotonic()
        elif self._call_id != model_call_id:
            self.flush()
            self._call_id = model_call_id
            self._index = delta.index
            self._started_at = monotonic()
        if len(self._content) + len(delta.content) > MAX_DELTA_BUFFER_CHARACTERS:
            self.flush()
            self._call_id = model_call_id
            self._index = delta.index
            self._started_at = monotonic()
        self._content += delta.content
        if self._seconds is not None and self._timer is None:
            self._timer = Timer(self._seconds, self._timed_flush, args=(self._timer_generation,))
            self._timer.daemon = True
            self._timer.start()
        elapsed = monotonic() - self._started_at if self._started_at is not None else 0.0
        if (self._characters is not None and len(self._content) >= self._characters) or (
            self._seconds is not None and elapsed >= self._seconds
        ):
            self.flush()

    def flush(self) -> None:
        with self._lock:
            self._raise_timer_error()
            self._flush_locked()

    def _flush_locked(self) -> None:
        self._cancel_timer()
        if self._call_id is None or not self._content:
            return
        self._emit_event(self._call_id, self._index, self._content)
        self._call_id = None
        self._content = ""
        self._started_at = None

    def _timed_flush(self, generation: int) -> None:
        with self._lock:
            if generation != self._timer_generation:
                return
            try:
                self._flush_locked()
            except Exception as error:
                self._timer_error = error

    def _cancel_timer(self) -> None:
        self._timer_generation += 1
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _raise_timer_error(self) -> None:
        if self._timer_error is not None:
            raise self._timer_error

    def _emit_event(self, model_call_id: str, index: int, content: str) -> None:
        self._sink(
            HarnessEventDraft(
                event_type=EventType.MODEL_RESPONSE_DELTA,
                actor=EventActor.HARNESS,
                payload={
                    "attempt_number": self._attempt_number,
                    "model_call_id": model_call_id,
                    "delta_index": index,
                    "content_delta": content,
                },
            )
        )
