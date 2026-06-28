from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True)
class ScmProxyRequest:
    provider: str
    action: str
    endpoint: str
    method: str = "POST"
    headers: tuple[tuple[str, str], ...] = ()
    secret_headers: tuple[tuple[str, str], ...] = ()
    body: dict[str, JsonValue] = field(default_factory=dict)
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _normalize_required(self.provider, "provider"))
        object.__setattr__(self, "action", _normalize_required(self.action, "action"))
        object.__setattr__(self, "endpoint", _normalize_required(self.endpoint, "endpoint"))
        object.__setattr__(self, "method", _normalize_required(self.method, "method").upper())
        object.__setattr__(self, "headers", _normalize_headers(self.headers))
        object.__setattr__(self, "secret_headers", _normalize_headers(self.secret_headers))
        object.__setattr__(self, "body", _normalize_json_object(self.body, "body"))
        object.__setattr__(self, "metadata", _normalize_json_object(self.metadata, "metadata"))

    def header_map(self) -> dict[str, str]:
        return dict(self.headers)

    def merged_header_map(self) -> dict[str, str]:
        return {
            **dict(self.headers),
            **dict(self.secret_headers),
        }

    def to_serializable(self) -> dict[str, JsonValue]:
        return {
            "provider": self.provider,
            "action": self.action,
            "endpoint": self.endpoint,
            "method": self.method,
            "headers": [{"name": name, "value": value} for name, value in self.headers],
            "body": self.body,
            "metadata": self.metadata,
        }

    def to_transport_payload(self) -> dict[str, JsonValue]:
        return {
            **self.to_serializable(),
            "secret_headers": [
                {"name": name, "value": value} for name, value in self.secret_headers
            ],
        }


@dataclass(frozen=True)
class ScmProxyResponse:
    status_code: int
    body: dict[str, JsonValue]
    headers: tuple[tuple[str, str], ...] = ()
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status_code < 100:
            raise ValueError("status_code must be >= 100")
        object.__setattr__(self, "body", _normalize_json_object(self.body, "body"))
        object.__setattr__(self, "headers", _normalize_headers(self.headers))
        object.__setattr__(self, "metadata", _normalize_json_object(self.metadata, "metadata"))

    def header_map(self) -> dict[str, str]:
        return dict(self.headers)

    def to_serializable(self) -> dict[str, JsonValue]:
        return {
            "status_code": self.status_code,
            "headers": [{"name": name, "value": value} for name, value in self.headers],
            "body": self.body,
            "metadata": self.metadata,
        }


class ScmProxyTransport(Protocol):
    def execute(self, request: ScmProxyRequest) -> ScmProxyResponse:
        raise NotImplementedError


def build_github_pull_request_proxy_request(
    *,
    endpoint: str,
    headers: dict[str, str],
    body: dict[str, JsonValue],
    token: str,
    credential_source: str | None,
    credential_backend: str | None,
) -> ScmProxyRequest:
    metadata: dict[str, JsonValue] = {}
    if credential_source is not None:
        metadata["credential_source"] = credential_source
    if credential_backend is not None:
        metadata["credential_backend"] = credential_backend
    return ScmProxyRequest(
        provider="github",
        action="pull_request.create",
        endpoint=endpoint,
        method="POST",
        headers=tuple(headers.items()),
        secret_headers=(("Authorization", f"Bearer {token.strip()}"),),
        body=body,
        metadata=metadata,
    )


def _normalize_required(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _normalize_headers(value: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    normalized: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name, header_value in value:
        normalized_name = _normalize_required(name, "header name")
        normalized_value = _normalize_required(header_value, "header value")
        if normalized_name.lower() in seen:
            raise ValueError(f"duplicate header: {normalized_name}")
        seen.add(normalized_name.lower())
        normalized.append((normalized_name, normalized_value))
    normalized.sort(key=lambda item: item[0].lower())
    return tuple(normalized)


def _normalize_json_object(
    value: dict[str, JsonValue],
    field_name: str,
) -> dict[str, JsonValue]:
    normalized: dict[str, JsonValue] = {}
    for key in sorted(value):
        if not isinstance(key, str):
            raise ValueError(f"{field_name} keys must be strings")
        normalized[key] = _normalize_json_value(value[key], field_name)
    return normalized


def _normalize_json_value(value: JsonValue, field_name: str) -> JsonValue:
    if isinstance(value, str):
        return value
    if isinstance(value, bool | int | float) or value is None:
        return value
    if isinstance(value, list):
        return [_normalize_json_value(item, field_name) for item in value]
    if isinstance(value, dict):
        return _normalize_json_object(value, field_name)
    raise ValueError(f"{field_name} must contain only JSON-serializable values")
