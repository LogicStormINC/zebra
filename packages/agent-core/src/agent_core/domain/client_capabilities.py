"""Frontend capability contracts for the Client Integration Plane.

ADR-CLIENT-01 freezes the rules implemented here: published profiles are
immutable per revision, digests are content-addressed over canonical JSON,
mounted snapshots can only narrow a published profile, and no executable
selector or business-write action can ever be published.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_CAPABILITY_NAME_LENGTH = 64
MAX_CAPABILITY_DESCRIPTION_LENGTH = 512
MAX_SCHEMA_BYTES = 8_192
MAX_RESULT_BYTES = 16_384
MAX_STATE_BYTES = 16_384
MAX_PROFILE_CONTRACTS = 128
MAX_PROFILE_BYTES = 262_144
MAX_ENUM_VALUES = 32
MAX_SCHEMA_DEPTH = 4
DIGEST_PATTERN = r"^[0-9a-f]{64}$"

CAPABILITY_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*(\.[a-z0-9-]+)+$")
FRONTEND_APP_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")
FORBIDDEN_FIELD_TOKENS = ("secret", "token", "password")
_SELECTOR_PATTERN = re.compile(
    r"^(#|\.|document\.|window\.|//)|javascript:|querySelector",
    re.IGNORECASE,
)
_ALLOWED_SCHEMA_KEYS = frozenset(
    {
        "type",
        "description",
        "properties",
        "required",
        "items",
        "enum",
        "additionalProperties",
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
    }
)
_ALLOWED_SCHEMA_TYPES = frozenset(
    {"object", "string", "integer", "number", "boolean", "array", "null"}
)


class ClientActionRisk(StrEnum):
    PRESENTATION = "presentation"
    NAVIGATION = "navigation"
    LOCAL_STATE = "local_state"
    USER_INTERACTION = "user_interaction"
    BUSINESS_WRITE_FORBIDDEN = "business_write_forbidden"


class ProfileLifecycle(StrEnum):
    PUBLISHED = "published"
    DEPRECATED = "deprecated"
    REVOKED = "revoked"


class ClientCapabilityError(ValueError):
    """Base error for frontend capability contract violations."""


class DuplicateClientCapabilityError(ClientCapabilityError):
    pass


class ForbiddenClientCapabilityFieldError(ClientCapabilityError):
    pass


class ClientCapabilitySizeError(ClientCapabilityError):
    pass


class ClientSelectorForbiddenError(ClientCapabilityError):
    pass


class UnpublishableClientActionRiskError(ClientCapabilityError):
    pass


class MountedCapabilityNarrowingError(ClientCapabilityError):
    pass


def canonical_client_capability_digest(payload: object) -> str:
    """Hash canonical JSON content; equal content always yields equal digest."""

    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _canonical_hash(payload: object) -> str:
    return canonical_client_capability_digest(payload)


def _validate_name(value: str) -> str:
    normalized = value.strip()
    if not CAPABILITY_NAME_PATTERN.fullmatch(normalized):
        raise ValueError(
            "capability names must be dot-namespaced lowercase identifiers"
            " such as 'trench.ui.event.open'"
        )
    if len(normalized) > MAX_CAPABILITY_NAME_LENGTH:
        raise ValueError("capability name exceeds the maximum length")
    return normalized


def _validate_description(value: str) -> str:
    if len(value) > MAX_CAPABILITY_DESCRIPTION_LENGTH:
        raise ValueError("capability description exceeds the maximum length")
    _reject_selector_text(value)
    return value


def _reject_selector_text(value: str) -> None:
    if _SELECTOR_PATTERN.search(value):
        raise ClientSelectorForbiddenError("executable selector strings are forbidden")


def _reject_forbidden_field_name(name: str) -> None:
    lowered = name.lower()
    for token in FORBIDDEN_FIELD_TOKENS:
        if token in lowered:
            raise ForbiddenClientCapabilityFieldError(
                f"field name '{name}' must not contain '{token}'"
            )


def _validate_restricted_json_schema(
    schema: object,
    *,
    field_name: str,
    depth: int = 0,
) -> None:
    """Reject anything outside a small, non-executable JSON Schema subset."""

    if not isinstance(schema, dict):
        raise ValueError(f"{field_name} must be a JSON object schema")
    if depth > MAX_SCHEMA_DEPTH:
        raise ClientCapabilitySizeError(f"{field_name} exceeds the maximum nesting depth")
    if len(json.dumps(schema, sort_keys=True, default=str)) > MAX_SCHEMA_BYTES:
        raise ClientCapabilitySizeError(f"{field_name} exceeds the maximum byte budget")
    for key in schema:
        if key not in _ALLOWED_SCHEMA_KEYS:
            raise ValueError(f"{field_name} uses unsupported schema key '{key}'")
    schema_type = schema.get("type")
    if schema_type is not None and schema_type not in _ALLOWED_SCHEMA_TYPES:
        raise ValueError(f"{field_name} uses unsupported schema type {schema_type!r}")
    description = schema.get("description")
    if isinstance(description, str):
        _reject_selector_text(description)
    enum_values = schema.get("enum")
    if enum_values is not None:
        if not isinstance(enum_values, list) or not enum_values:
            raise ValueError(f"{field_name} enum must be a non-empty list")
        if len(enum_values) > MAX_ENUM_VALUES:
            raise ClientCapabilitySizeError(f"{field_name} exceeds the maximum enum size")
        for item in enum_values:
            if isinstance(item, str):
                _reject_selector_text(item)
    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, dict) or not properties:
            raise ValueError(f"{field_name} properties must be a non-empty object")
        for name, child in properties.items():
            _reject_forbidden_field_name(str(name))
            _validate_restricted_json_schema(
                child, field_name=f"{field_name}.{name}", depth=depth + 1
            )
    items = schema.get("items")
    if items is not None:
        _validate_restricted_json_schema(
            items, field_name=f"{field_name}[]", depth=depth + 1
        )
    required = schema.get("required")
    if required is not None:
        if not isinstance(required, list) or not required:
            raise ValueError(f"{field_name} required must be a non-empty list")
        for name in required:
            _reject_forbidden_field_name(str(name))
    additional = schema.get("additionalProperties")
    if additional is not None and additional is not False:
        raise ValueError(f"{field_name} additionalProperties may only be false")


class ClientReadableContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description: str = ""
    state_schema: dict[str, Any] = Field(default_factory=dict)
    max_state_bytes: int = Field(default=MAX_STATE_BYTES)

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        return _validate_name(value)

    @field_validator("description")
    @classmethod
    def _check_description(cls, value: str) -> str:
        return _validate_description(value)

    @field_validator("state_schema")
    @classmethod
    def _check_state_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        if value:
            _validate_restricted_json_schema(value, field_name="state_schema")
        return value

    @model_validator(mode="after")
    def _check_bounds(self) -> ClientReadableContract:
        if not 0 < self.max_state_bytes <= MAX_STATE_BYTES:
            raise ValueError("max_state_bytes must stay within the platform bound")
        return self


class ClientActionContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    result_schema: dict[str, Any] = Field(default_factory=dict)
    risk: ClientActionRisk
    max_result_bytes: int = Field(default=MAX_RESULT_BYTES)

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        return _validate_name(value)

    @field_validator("description")
    @classmethod
    def _check_description(cls, value: str) -> str:
        return _validate_description(value)

    @field_validator("parameters", "result_schema")
    @classmethod
    def _check_schema(cls, value: dict[str, Any], info) -> dict[str, Any]:
        if value:
            _validate_restricted_json_schema(value, field_name=str(info.field_name))
        return value

    @model_validator(mode="after")
    def _check_bounds(self) -> ClientActionContract:
        if not 0 < self.max_result_bytes <= MAX_RESULT_BYTES:
            raise ValueError("max_result_bytes must stay within the platform bound")
        return self


class ClientComponentContract(BaseModel):
    """Placeholder contract; component generative UI stays locked in V1."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description: str = ""

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        return _validate_name(value)

    @field_validator("description")
    @classmethod
    def _check_description(cls, value: str) -> str:
        return _validate_description(value)


class FrontendCapabilityProfileVersion(BaseModel):
    """Immutable per-revision capability set; the configuration source of truth."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    frontend_app_id: str
    revision: int = Field(ge=1)
    readables: tuple[ClientReadableContract, ...] = ()
    actions: tuple[ClientActionContract, ...] = ()
    components: tuple[ClientComponentContract, ...] = ()
    lifecycle: ProfileLifecycle = ProfileLifecycle.PUBLISHED
    published_at: datetime | None = None

    @field_validator("frontend_app_id")
    @classmethod
    def _check_app_id(cls, value: str) -> str:
        normalized = value.strip()
        if not FRONTEND_APP_ID_PATTERN.fullmatch(normalized):
            raise ValueError("frontend_app_id must be a lowercase slug")
        return normalized

    @model_validator(mode="after")
    def _check_uniqueness(self) -> FrontendCapabilityProfileVersion:
        names: list[str] = []
        for contract in (self.readables, self.actions, self.components):
            names.extend(item.name for item in contract)
        if len(set(names)) != len(names):
            raise DuplicateClientCapabilityError(
                "action, readable and component names must be unique within a profile"
            )
        total = len(names)
        if total > MAX_PROFILE_CONTRACTS:
            raise ClientCapabilitySizeError(
                f"profiles may declare at most {MAX_PROFILE_CONTRACTS} contracts"
            )
        return self

    @property
    def profile_digest(self) -> str:
        payload = self.model_dump(
            mode="json",
            exclude={"lifecycle", "published_at"},
        )
        return _canonical_hash(payload)

    def readable_names(self) -> frozenset[str]:
        return frozenset(item.name for item in self.readables)

    def action_names(self) -> frozenset[str]:
        return frozenset(item.name for item in self.actions)

    def action_contract(self, name: str) -> ClientActionContract | None:
        for action in self.actions:
            if action.name == name:
                return action
        return None


def validate_profile_for_publish(profile: FrontendCapabilityProfileVersion) -> None:
    """Enforce the publish gate; storage layers call this before inserting."""

    for action in profile.actions:
        if action.risk is ClientActionRisk.BUSINESS_WRITE_FORBIDDEN:
            raise UnpublishableClientActionRiskError(
                f"action {action.name} carries business_write_forbidden risk"
                " and cannot be published"
            )
    serialized = json.dumps(
        profile.model_dump(mode="json", exclude={"lifecycle", "published_at"}),
        sort_keys=True,
    )
    if len(serialized.encode()) > MAX_PROFILE_BYTES:
        raise ClientCapabilitySizeError("profile exceeds the maximum serialized size")


class FrontendCapabilityBinding(BaseModel):
    """Namespace binding of one published profile revision for one host."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    binding_id: UUID
    deployment_namespace: str
    host_app_id: str
    namespace_id: str
    frontend_app_id: str
    revision: int = Field(ge=1)
    profile_digest: str = Field(pattern=DIGEST_PATTERN)
    binding_revision: int = Field(ge=1)
    bound_at: datetime

    @property
    def binding_digest(self) -> str:
        payload = self.model_dump(
            mode="json",
            exclude={"binding_revision", "bound_at"},
        )
        return _canonical_hash(payload)


class MountedCapabilitySnapshot(BaseModel):
    """Runtime mount report; must be a subset of a published profile."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_session_id: UUID
    frontend_app_id: str
    profile_revision: int = Field(ge=1)
    profile_digest: str = Field(pattern=DIGEST_PATTERN)
    mounted_readables: tuple[str, ...] = ()
    mounted_actions: tuple[str, ...] = ()
    ui_revision: int = Field(ge=0)
    mounted_at: datetime

    @model_validator(mode="after")
    def _check_names(self) -> MountedCapabilitySnapshot:
        for group in (self.mounted_readables, self.mounted_actions):
            if len(set(group)) != len(group):
                raise DuplicateClientCapabilityError("mounted names must be unique")
        return self

    @property
    def snapshot_digest(self) -> str:
        payload = self.model_dump(mode="json", exclude={"mounted_at"})
        return _canonical_hash(payload)

    def ensure_subset_of(self, profile: FrontendCapabilityProfileVersion) -> None:
        if profile.frontend_app_id != self.frontend_app_id:
            raise MountedCapabilityNarrowingError("snapshot references a different app")
        if profile.revision != self.profile_revision:
            raise MountedCapabilityNarrowingError("snapshot revision does not match")
        if profile.profile_digest != self.profile_digest:
            raise MountedCapabilityNarrowingError("snapshot digest does not match")
        unknown = set(self.mounted_readables) - profile.readable_names()
        if unknown:
            raise MountedCapabilityNarrowingError(
                f"readables not published: {sorted(unknown)}"
            )
        unknown_actions = set(self.mounted_actions) - profile.action_names()
        if unknown_actions:
            raise MountedCapabilityNarrowingError(
                f"actions not published: {sorted(unknown_actions)}"
            )
