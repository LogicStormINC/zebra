"""Broker wakeup hints only: validation never grants runtime authority."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

MAX_RAW_BYTES = 16_384
MAX_DEPTH = 8


def _identifier(value: str) -> str:
    if not value.strip() or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value):
        raise ValueError("identifier must be nonblank and contain no control characters")
    return value


OpaqueId = Annotated[
    str, Field(strict=True, min_length=1, max_length=256), AfterValidator(_identifier)
]
Namespace = Annotated[
    str, Field(strict=True, min_length=1, max_length=128), AfterValidator(_identifier)
]
CanonicalUUID = Annotated[
    str,
    Field(strict=True, pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
]
NonnegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]


def _timestamp(value: str) -> str:
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value
    ):
        raise ValueError("occurred_at must be a timezone-aware RFC3339 timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("occurred_at requires a timezone")
    # fromisoformat normalizes invalid offset minutes; reject those explicitly.
    if value[-1] != "Z" and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        raise ValueError("invalid RFC3339 timezone offset")
    return value


def _traceparent(value: str) -> str:
    if not re.fullmatch(r"00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}", value):
        raise ValueError("traceparent must use W3C version 00")
    if value[3:35] == "0" * 32 or value[36:52] == "0" * 16:
        raise ValueError("traceparent trace and span IDs must be nonzero")
    return value


Timestamp = Annotated[
    str,
    Field(strict=True, max_length=128, json_schema_extra={"format": "date-time"}),
    AfterValidator(_timestamp),
]
Traceparent = Annotated[
    str,
    Field(
        strict=True,
        min_length=55,
        max_length=55,
        pattern=r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$",
    ),
    AfterValidator(_traceparent),
]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)


class PrincipalScope(FrozenModel):
    kind: Literal["principal"]
    tenant_id: OpaqueId
    workspace_id: OpaqueId


class SharedSourceScope(FrozenModel):
    kind: Literal["shared_source"]
    service_scope_id: OpaqueId


class TurnRef(FrozenModel):
    kind: Literal["trench_turn"]
    id: OpaqueId


class ZebraCommandRef(FrozenModel):
    kind: Literal["zebra_command"]
    id: OpaqueId


class SourceFetchRef(FrozenModel):
    kind: Literal["source_fetch_command"]
    id: OpaqueId


class EnvelopeFields(FrozenModel):
    message_id: CanonicalUUID
    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    deployment_namespace: Namespace
    aggregate_id: OpaqueId
    operation_id: OpaqueId
    wake_generation: NonnegativeInt
    idempotency_key: OpaqueId
    correlation_id: OpaqueId
    causation_id: OpaqueId | None
    occurred_at: Timestamp
    traceparent: Traceparent | None
    payload_ref: TurnRef | ZebraCommandRef | SourceFetchRef

    @model_validator(mode="after")
    def match_operation(self) -> Self:
        if self.payload_ref.id != self.operation_id:
            raise ValueError("payload_ref.id must equal operation_id")
        return self


class TurnEnvelope(EnvelopeFields):
    message_type: Literal["trench.ai.turn.ready"]
    scope: PrincipalScope
    payload_ref: TurnRef

    @model_validator(mode="after")
    def match_turn(self) -> Self:
        if self.aggregate_id != self.operation_id:
            raise ValueError("turn aggregate_id must equal operation_id")
        return self


class ZebraCommandEnvelope(EnvelopeFields):
    message_type: Literal["zebra.session.command.ready"]
    scope: PrincipalScope
    payload_ref: ZebraCommandRef
    accepted_event_id: CanonicalUUID
    accepted_sequence: PositiveInt


class SourceFetchEnvelope(EnvelopeFields):
    message_type: Literal["trench.source.fetch.ready"]
    scope: Annotated[PrincipalScope | SharedSourceScope, Field(discriminator="kind")]
    payload_ref: SourceFetchRef


BrokerEnvelope = Annotated[
    TurnEnvelope | ZebraCommandEnvelope | SourceFetchEnvelope,
    Field(discriminator="message_type"),
]
_ADAPTER: TypeAdapter[BrokerEnvelope] = TypeAdapter(BrokerEnvelope)


def broker_envelope_json_schema() -> dict[str, Any]:
    """Return the reproducible shape schema; see docs for semantic limits."""
    return _ADAPTER.json_schema()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"nonfinite JSON number: {value}")


def _check_depth(value: Any, depth: int = 0) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("nonfinite JSON number")
    if isinstance(value, dict | list):
        if depth >= MAX_DEPTH:
            raise ValueError("JSON structure exceeds maximum depth")
        children = value.values() if isinstance(value, dict) else value
        for child in children:
            _check_depth(child, depth + 1)


def parse_broker_envelope(raw: bytes) -> BrokerEnvelope:
    """Decode bounded untrusted UTF-8 JSON without resolving referenced objects."""
    if not isinstance(raw, bytes):
        raise TypeError("raw envelope must be bytes")
    if len(raw) > MAX_RAW_BYTES:
        raise ValueError("broker envelope exceeds 16384 bytes")
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except (UnicodeError, RecursionError):
        raise ValueError("invalid UTF-8 JSON or excessive nesting") from None
    _check_depth(value)
    try:
        return _ADAPTER.validate_python(value)
    except ValidationError:
        raise ValueError("invalid broker envelope contract") from None
