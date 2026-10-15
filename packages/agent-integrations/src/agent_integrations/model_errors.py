from __future__ import annotations

import json
import logging
from time import perf_counter

import httpx
from agent_core.domain.modeling import ModelCompletion


class ModelProviderError(RuntimeError):
    def __init__(
        self,
        normalized_error: str,
        *,
        retryable: bool,
        retry_count: int = 0,
    ) -> None:
        super().__init__(f"model provider request failed: {normalized_error}")
        self.normalized_error = normalized_error
        self.retryable = retryable
        self.retry_count = retry_count


def normalize_provider_error(exc: Exception) -> ModelProviderError:
    if isinstance(exc, ModelProviderError):
        return exc
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        category, retryable = {
            400: ("invalid_request", False),
            401: ("authentication_failed", False),
            402: ("insufficient_balance", False),
            422: ("invalid_parameters", False),
            429: ("rate_limited", True),
            500: ("provider_error", True),
            503: ("provider_unavailable", True),
        }.get(status, ("http_error", status >= 500))
        return ModelProviderError(category, retryable=retryable)
    if isinstance(exc, httpx.TimeoutException | httpx.TransportError):
        return ModelProviderError("transport_error", retryable=True)
    return ModelProviderError("invalid_provider_response", retryable=False)


def finish_reason_error(finish_reason: str | None) -> ModelProviderError | None:
    if finish_reason is None or finish_reason in {"stop", "tool_calls"}:
        return None
    category, retryable = {
        "length": ("output_truncated", False),
        "content_filter": ("content_filtered", False),
        "insufficient_system_resource": ("insufficient_system_resource", True),
    }.get(finish_reason, ("unsupported_finish_reason", False))
    return ModelProviderError(category, retryable=retryable)


def log_provider_attempt(
    call_id: str,
    attempt: int,
    started: float,
    attempt_started: float,
    *,
    completion: ModelCompletion | None = None,
    error: Exception | None = None,
) -> None:
    # ponytail: one bounded log per attempt, never per delta or persisted as events.
    fields: dict[str, object] = {
        "call_id": call_id,
        "attempt": attempt,
        "outcome": "failed" if error is not None else "completed",
        "attempt_latency_ms": int((perf_counter() - attempt_started) * 1000),
        "call_elapsed_ms": int((perf_counter() - started) * 1000),
    }
    if error is not None:
        fields.update(
            error_type=type(error).__name__,
            normalized_error=normalize_provider_error(error).normalized_error,
            http_status=error.response.status_code
            if isinstance(error, httpx.HTTPStatusError)
            else None,
        )
    if completion is not None:
        metadata = completion.call_metadata
        public_ms = metadata.time_to_first_public_text_ms
        fields.update(
            attempt_first_event_ms=metadata.time_to_first_event_ms,
            attempt_first_public_text_ms=public_ms,
            call_to_successful_attempt_public_text_ms=(
                int((attempt_started - started) * 1000) + public_ms
                if public_ms is not None
                else None
            ),
        )
    # Do not attach exception text, exc_info, headers, URL, payload or model reasoning.
    logger = logging.getLogger(__name__)
    # Workers may retain only warnings: keep failed attempts and recovered retries visible.
    log = logger.warning if error is not None or attempt > 1 else logger.info
    log("model_provider_attempt %s", json.dumps(fields))
