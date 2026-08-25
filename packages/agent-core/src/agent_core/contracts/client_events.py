"""Payload contracts for durable client integration events."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ClientEffectScheduledPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_number: int = Field(ge=1)
    tool_name: str
    tool_call_id: str
    client_effect_id: str
    action_name: str
    arguments: dict[str, object] = Field(default_factory=dict)
    action_contract_digest: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    client_binding_digest: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    expected_ui_revision: int = Field(default=0, ge=0)
    idempotency_key: str = ""
    request_digest: str = ""
    assistant_message: str | None = Field(default=None, exclude_if=lambda value: value is None)
    conversation: list[dict[str, object]] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    model_calls_used: int = Field(default=0, ge=0)
    tool_calls_executed: int = Field(default=0, ge=0)

    @field_validator("tool_name", "tool_call_id", "client_effect_id", "action_name")
    @classmethod
    def ensure_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("client effect scheduled fields must not be blank")
        return value


class ClientEffectReceiptAcceptedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_effect_id: str
    receipt_id: str
    status: str
    request_digest: str = ""
    replayed: bool = False


class SessionWaitingForClientEffectPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = "waiting_client_effect"
    client_effect_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)
