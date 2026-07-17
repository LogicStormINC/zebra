from __future__ import annotations

import httpx


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
