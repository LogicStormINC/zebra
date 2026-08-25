"""Durable client effects: persisted browser action requests and receipts.

ADR-CLIENT-01: every effect pins the action contract digest, the client
binding digest, the fence hash and the expected UI revision; stale fences,
stale revisions and expired effects all fail closed; one effect accepts at
most one semantically-consistent terminal receipt.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.identifiers import (
    ClientEffectId,
    ClientSessionId,
    SessionId,
    TaskId,
    ToolCallId,
)

MAX_EFFECT_ARGUMENTS_BYTES = 16_384
MAX_RECEIPT_RESULT_BYTES = 16_384
RECEIPT_FORBIDDEN_KEYS = ("token", "cookie", "secret", "dom", "password", "authorization")


class ClientEffectStatus(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DECLINED = "declined"
    UNAVAILABLE = "unavailable"
    STALE_UI_STATE = "stale_ui_state"
    EXPIRED = "expired"
    UNCERTAIN = "uncertain"
    CANCELLED = "cancelled"


#: Statuses a browser receipt may carry; expiry is decided server-side.
RECEIPT_TERMINAL_STATUSES = frozenset(
    {
        ClientEffectStatus.SUCCEEDED,
        ClientEffectStatus.FAILED,
        ClientEffectStatus.DECLINED,
        ClientEffectStatus.UNAVAILABLE,
        ClientEffectStatus.STALE_UI_STATE,
    }
)

#: Fully resolved statuses; uncertain requires explicit resolution first.
CLIENT_EFFECT_TERMINAL_STATUSES = frozenset(
    RECEIPT_TERMINAL_STATUSES
    | {
        ClientEffectStatus.EXPIRED,
        ClientEffectStatus.CANCELLED,
    }
)


class ClientEffectError(ValueError):
    """Base error for client effect contract violations."""


class ClientEffectFenceError(ClientEffectError):
    pass


class ClientEffectRevisionError(ClientEffectError):
    pass


class ClientEffectExpiredError(ClientEffectError):
    pass


class ClientEffectIdempotencyConflict(ClientEffectError):
    pass


class ClientEffectReceiptConflict(ClientEffectError):
    pass


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _json_bytes(value: object, *, label: str) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    except (TypeError, ValueError) as exc:
        raise ClientEffectError(f"{label} must be JSON-compatible") from exc


def _check_receipt_keys(value: object, *, depth: int = 0) -> None:
    if depth > 16:
        raise ClientEffectError("receipt result nesting exceeds the depth budget")
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = str(key).lower()
            for token in RECEIPT_FORBIDDEN_KEYS:
                if token in lowered:
                    raise ClientEffectError(f"receipt results must not carry '{token}' fields")
            _check_receipt_keys(nested, depth=depth + 1)
    elif isinstance(value, list):
        for nested in value:
            _check_receipt_keys(nested, depth=depth + 1)


class ClientEffectRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    effect_id: ClientEffectId
    task_id: TaskId
    parent_session_id: SessionId
    run_id: str = Field(min_length=1, max_length=128)
    client_session_id: ClientSessionId
    tool_call_id: ToolCallId
    action_name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, object] = Field(default_factory=dict)
    action_contract_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    client_binding_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    fence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_ui_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=160)
    requested_at: datetime
    expires_at: datetime
    status: ClientEffectStatus = ClientEffectStatus.PENDING

    @field_validator("arguments")
    @classmethod
    def _check_arguments(cls, value: dict[str, object]) -> dict[str, object]:
        if len(_json_bytes(value, label="effect arguments")) > MAX_EFFECT_ARGUMENTS_BYTES:
            raise ClientEffectError("effect arguments exceed the byte budget")
        return value

    @field_validator("requested_at", "expires_at")
    @classmethod
    def _check_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ClientEffectError("effect timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _check_expiry(self) -> ClientEffectRequest:
        if self.expires_at <= self.requested_at:
            raise ValueError("effect expiry must be after the request time")
        return self

    @property
    def request_digest(self) -> str:
        payload = self.model_dump(
            mode="json",
            exclude={"effect_id", "status", "requested_at", "expires_at"},
        )
        return _canonical_hash(payload)

    def is_expired(self, *, now: datetime | None = None) -> bool:
        moment = now or datetime.now(UTC)
        return moment >= self.expires_at

    def ensure_receiptable(
        self,
        *,
        current_ui_revision: int,
        now: datetime | None = None,
    ) -> None:
        if self.is_expired(now=now):
            raise ClientEffectExpiredError("expired effects reject receipts")
        if self.status in CLIENT_EFFECT_TERMINAL_STATUSES:
            raise ClientEffectReceiptConflict("effect already resolved by a terminal receipt")
        if current_ui_revision != self.expected_ui_revision:
            raise ClientEffectRevisionError(
                "stale UI revision; the action was scheduled against an older page state"
            )


class ClientEffectReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    receipt_id: UUID
    effect_id: ClientEffectId
    idempotency_key: str = Field(min_length=8, max_length=160)
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: ClientEffectStatus
    result: dict[str, object] = Field(default_factory=dict)
    controller: bool = True
    received_at: datetime

    @field_validator("status")
    @classmethod
    def _check_status(cls, value: ClientEffectStatus) -> ClientEffectStatus:
        if value not in RECEIPT_TERMINAL_STATUSES:
            raise ClientEffectReceiptConflict(
                f"receipt status {value!r} is not an acceptable terminal state"
            )
        return value

    @field_validator("result")
    @classmethod
    def _check_result(cls, value: dict[str, object]) -> dict[str, object]:
        if len(_json_bytes(value, label="receipt result")) > MAX_RECEIPT_RESULT_BYTES:
            raise ClientEffectError("receipt result exceeds the byte budget")
        _check_receipt_keys(value)
        return value

    @field_validator("received_at")
    @classmethod
    def _check_received_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ClientEffectError("receipt timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _check_controller(self) -> ClientEffectReceipt:
        if not self.controller:
            raise ClientEffectError(
                "observers cannot submit receipts; only the active controller can"
            )
        return self

    def matches(self, request: ClientEffectRequest) -> bool:
        return (
            self.effect_id == request.effect_id
            and self.idempotency_key == request.idempotency_key
            and self.request_digest == request.request_digest
        )


ReceiptAdmission = Literal["accept", "replay", "conflict"]


def decide_receipt_admission(
    request: ClientEffectRequest,
    existing: ClientEffectReceipt | None,
    incoming: ClientEffectReceipt,
) -> ReceiptAdmission:
    """One effect accepts at most one semantically consistent receipt."""

    if not incoming.matches(request):
        return "conflict"
    if existing is None:
        return "accept"
    if (
        existing.idempotency_key == incoming.idempotency_key
        and existing.status is incoming.status
        and existing.result == incoming.result
    ):
        return "replay"
    return "conflict"


IdempotencyDecision = Literal["schedule", "replay", "conflict"]


def resolve_effect_idempotency(
    *,
    idempotency_key: str,
    request_digest: str,
    existing: ClientEffectRequest | None,
) -> IdempotencyDecision:
    if existing is None:
        return "schedule"
    if existing.idempotency_key != idempotency_key:
        return "schedule"
    if existing.request_digest == request_digest:
        return "replay"
    raise ClientEffectIdempotencyConflict(
        "the same idempotency key was reused with a different request digest"
    )


class ClientEffectContinuation(BaseModel):
    """Frozen resume state captured when the effect is scheduled."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    effect_id: ClientEffectId
    task_id: TaskId
    run_id: str
    tool_call_id: ToolCallId
    action_name: str
    assistant_message: str = ""
    model_calls_used: int = Field(default=0, ge=0)
    tool_calls_executed: int = Field(default=0, ge=0)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _check_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ClientEffectError("continuation timestamp must be timezone-aware")
        return value.astimezone(UTC)


def client_effect_idempotency_key(
    *,
    task_id: TaskId,
    run_id: str,
    tool_call_id: ToolCallId,
) -> str:
    return f"client-effect:{task_id}:{run_id}:{tool_call_id}"
