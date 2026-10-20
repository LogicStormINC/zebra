"""Historical joint Trench/Runtime wire contract; select explicitly at composition."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from agent_core.contracts.broker_envelope import (
    CanonicalUUID,
    FrozenModel,
    Namespace,
    NonnegativeInt,
    OpaqueId,
    PositiveInt,
    PrincipalScope,
    Timestamp,
    Traceparent,
    ZebraCommandRef,
    _decode_broker_json,
)
from pydantic import Field, TypeAdapter, ValidationError, model_validator


class SharedSourceScope(FrozenModel):
    kind: Literal["shared_source"]
    service_scope_id: OpaqueId


class TurnRef(FrozenModel):
    kind: Literal["trench_turn"]
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


def parse_broker_envelope(raw: bytes) -> BrokerEnvelope:
    """Decode the historical joint contract with the same strict wire bounds."""
    try:
        return _ADAPTER.validate_python(_decode_broker_json(raw))
    except ValidationError:
        raise ValueError("invalid broker envelope contract") from None
