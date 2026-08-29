"""Bound provider text chunks before they enter the durable Event stream."""

from collections.abc import Callable
from time import monotonic

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.modeling import ModelTextDelta
from agent_core.harness.models import HarnessEventDraft


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
        self.reset()

    def reset(self) -> None:
        self._call_id: str | None = None
        self._index = 0
        self._content = ""
        self._started_at: float | None = None
        self._first_emitted = False

    def emit(self, model_call_id: str, delta: ModelTextDelta) -> None:
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
        self._content += delta.content
        elapsed = monotonic() - self._started_at if self._started_at is not None else 0.0
        if (self._characters is not None and len(self._content) >= self._characters) or (
            self._seconds is not None and elapsed >= self._seconds
        ):
            self.flush()

    def flush(self) -> None:
        if self._call_id is None or not self._content:
            return
        self._emit_event(self._call_id, self._index, self._content)
        self._call_id = None
        self._content = ""
        self._started_at = None

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
