from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from time import perf_counter
from typing import Any

import httpx
from agent_core.domain.modeling import ModelTextDelta
from agent_core.ports.model_gateway import ModelResponseRejectedError

from agent_integrations.model_errors import ModelProviderError


def read_deepseek_responses_stream(
    client: httpx.Client,
    *,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    on_text_delta: Callable[[ModelTextDelta], None],
) -> dict[str, Any]:
    """Read one stateless Responses SSE stream through its semantic terminal event."""

    started = perf_counter()
    first_event_ms: int | None = None
    first_public_text_ms: int | None = None
    last_sequence = -1
    delta_index = 0
    terminal: dict[str, Any] | None = None
    with client.stream("POST", url, headers=headers, json=body) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            raw = line.removeprefix("data:").strip()
            if not raw:
                continue
            payload = _event_payload(raw)
            sequence = payload.get("sequence_number")
            if (
                not isinstance(sequence, int)
                or isinstance(sequence, bool)
                or sequence <= last_sequence
            ):
                raise _rejected(raw, "invalid_responses_sequence")
            last_sequence = sequence
            elapsed_ms = int((perf_counter() - started) * 1000)
            if first_event_ms is None:
                first_event_ms = elapsed_ms
            event_type = payload.get("type")
            if not isinstance(event_type, str):
                raise _rejected(raw, "invalid_responses_event_type")
            if event_type == "response.output_text.delta":
                delta = payload.get("delta")
                if not isinstance(delta, str):
                    raise _rejected(raw, "invalid_responses_text_delta")
                if delta:
                    on_text_delta(ModelTextDelta(index=delta_index, content=delta))
                    delta_index += 1
                    if first_public_text_ms is None:
                        first_public_text_ms = elapsed_ms
            if event_type == "response.failed":
                raise ModelProviderError("provider_response_failed", retryable=True)
            if event_type in {"response.completed", "response.incomplete"}:
                response_payload = payload.get("response")
                if not isinstance(response_payload, dict):
                    raise _rejected(raw, "invalid_responses_terminal")
                terminal = dict(response_payload)
                break
    if terminal is None:
        raise ModelResponseRejectedError(
            "responses_terminal_missing",
            phase="stream_terminal",
            retryable=True,
        )
    terminal["_zebra_time_to_first_event_ms"] = first_event_ms
    terminal["_zebra_time_to_first_public_text_ms"] = first_public_text_ms
    return terminal


def _event_payload(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _rejected(raw, "invalid_responses_event_json", error_position=exc.pos) from exc
    if not isinstance(payload, dict):
        raise _rejected(raw, "invalid_responses_event_shape")
    return payload


def _rejected(
    raw: str,
    reason: str,
    *,
    error_position: int | None = None,
) -> ModelResponseRejectedError:
    encoded = raw.encode("utf-8")
    return ModelResponseRejectedError(
        reason,
        phase="stream_event",
        retryable=True,
        error_position=error_position,
        payload_size=len(encoded),
        payload_sha256=hashlib.sha256(encoded).hexdigest(),
    )
