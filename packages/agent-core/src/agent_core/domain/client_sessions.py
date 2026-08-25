"""Client sessions, grants and control fencing for the browser plane.

ADR-CLIENT-01: a browser tab holds one client session established by a
Host-BFF-issued grant; at most one active controller lease exists per run;
fence token values never enter events or logs (only their sha256 hash).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_core.domain.identifiers import ClientSessionId, new_client_session_id

DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CLIENT_SCOPE_PATTERN = re.compile(r"^client\.[a-z0-9._-]{1,48}$")
ORIGIN_PATTERN = re.compile(r"^https://[a-z0-9.-]+(?::\d{1,5})?$", re.IGNORECASE)
MAX_CLIENT_SCOPES = 16
MAX_USER_REF_LENGTH = 128
MIN_FENCE_TOKEN_LENGTH = 16
DEFAULT_CLIENT_SESSION_TTL = timedelta(hours=12)
DEFAULT_CONTROL_LEASE_TTL = timedelta(minutes=5)


class ClientSessionStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CLOSED = "closed"


class ClientControllerRole(StrEnum):
    CONTROLLER = "controller"
    OBSERVER = "observer"


class ClientSessionError(ValueError):
    """Base error for client session and control-lease violations."""


class ClientGrantError(ClientSessionError):
    pass


class ClientSessionExpiredError(ClientSessionError):
    pass


class ClientControlLeaseError(ClientSessionError):
    pass


class ClientFenceError(ClientSessionError):
    pass


class ClientObserverActionError(ClientSessionError):
    pass


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class ClientSessionGrant(BaseModel):
    """Grant issued by the Host BFF; never a HostGrant substitute."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    grant_id: UUID
    host_app_id: str
    namespace_id: str
    frontend_app_id: str
    origin: str
    user_ref: str
    profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    scopes: tuple[str, ...] = ()
    expires_at: datetime

    @field_validator("origin")
    @classmethod
    def _check_origin(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not ORIGIN_PATTERN.fullmatch(normalized):
            raise ValueError("grant origin must be a bare https origin")
        return normalized

    @field_validator("user_ref")
    @classmethod
    def _check_user_ref(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > MAX_USER_REF_LENGTH:
            raise ValueError("user_ref must be a bounded opaque identifier")
        return normalized

    @field_validator("scopes")
    @classmethod
    def _check_scopes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > MAX_CLIENT_SCOPES:
            raise ValueError(f"grants carry at most {MAX_CLIENT_SCOPES} client scopes")
        normalized = tuple(scope.strip() for scope in value)
        if len(set(normalized)) != len(normalized):
            raise ValueError("grant scopes must be unique")
        for scope in normalized:
            if not CLIENT_SCOPE_PATTERN.fullmatch(scope):
                raise ClientGrantError(f"scope {scope!r} is not a client capability scope")
        return normalized

    @field_validator("expires_at")
    @classmethod
    def _check_expiry_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ClientGrantError("grant expiry must be timezone-aware")
        return value.astimezone(UTC)

    @property
    def grant_digest(self) -> str:
        return _canonical_hash(self.model_dump(mode="json"))

    def ensure_matches(
        self,
        *,
        host_app_id: str,
        namespace_id: str,
        frontend_app_id: str,
        origin: str,
    ) -> None:
        """Fail closed on any namespace or origin drift."""

        mismatches = [
            (name, expected, actual)
            for name, expected, actual in (
                ("host_app_id", host_app_id, self.host_app_id),
                ("namespace_id", namespace_id, self.namespace_id),
                ("frontend_app_id", frontend_app_id, self.frontend_app_id),
                ("origin", self.origin.rstrip("/"), origin.rstrip("/")),
            )
            if expected != actual
        ]
        if mismatches:
            raise ClientGrantError(f"grant drift: {mismatches}")


class ClientControlFence(BaseModel):
    """Bearer fence for controller actions; only the hash is ever persisted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    token: str = Field(min_length=MIN_FENCE_TOKEN_LENGTH)

    @field_validator("token")
    @classmethod
    def _check_token(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < MIN_FENCE_TOKEN_LENGTH or any(ch.isspace() for ch in normalized):
            raise ValueError("fence token must be a compact opaque string")
        return normalized

    @classmethod
    def issue(cls) -> ClientControlFence:
        return cls(token=uuid4().hex + uuid4().hex)

    @property
    def fence_hash(self) -> str:
        return hashlib.sha256(self.token.encode()).hexdigest()

    def matches_hash(self, expected_hash: str) -> bool:
        return self.fence_hash == expected_hash


class ClientSessionCredential(BaseModel):
    """One-time session bearer; only its hash is persisted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    token: str = Field(min_length=MIN_FENCE_TOKEN_LENGTH)

    @field_validator("token")
    @classmethod
    def _check_token(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < MIN_FENCE_TOKEN_LENGTH or any(ch.isspace() for ch in normalized):
            raise ValueError("session credential must be a compact opaque string")
        return normalized

    @classmethod
    def issue(cls) -> ClientSessionCredential:
        return cls(token=uuid4().hex + uuid4().hex)

    @property
    def credential_hash(self) -> str:
        return hashlib.sha256(self.token.encode()).hexdigest()


class ClientSession(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: ClientSessionId = Field(default_factory=new_client_session_id)
    grant: ClientSessionGrant
    credential_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: ClientSessionStatus = ClientSessionStatus.ACTIVE
    created_at: datetime
    heartbeat_at: datetime | None = None
    expires_at: datetime
    mounted_snapshot_digest: str | None = None
    ui_revision: int = Field(default=0)

    @field_validator("created_at", "heartbeat_at", "expires_at")
    @classmethod
    def _check_session_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ClientSessionError("session timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _check_expiry(self) -> ClientSession:
        if self.expires_at <= self.created_at:
            raise ValueError("session expiry must be after creation")
        return self

    def is_expired(self, *, now: datetime | None = None) -> bool:
        moment = now or datetime.now(UTC)
        return (
            moment >= min(self.expires_at, self.grant.expires_at)
            or self.status is ClientSessionStatus.EXPIRED
        )

    def matches_credential(self, credential: ClientSessionCredential) -> bool:
        return credential.credential_hash == self.credential_hash

    def ensure_active(self, *, now: datetime | None = None) -> None:
        if self.is_expired(now=now):
            raise ClientSessionExpiredError("client session is expired")
        if self.status is ClientSessionStatus.CLOSED:
            raise ClientSessionExpiredError("client session is closed")

    def ensure_renewable(self, *, now: datetime | None = None) -> None:
        """Expired sessions can never renew; only active sessions heartbeat."""

        self.ensure_active(now=now)


class ClientControlLease(BaseModel):
    """At most one active controller lease exists per run binding."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_binding_id: UUID
    client_session_id: ClientSessionId
    role: ClientControllerRole = ClientControllerRole.CONTROLLER
    fence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    acquired_at: datetime
    heartbeat_at: datetime
    expires_at: datetime

    def is_expired(self, *, now: datetime | None = None) -> bool:
        moment = now or datetime.now(UTC)
        return moment >= self.expires_at

    def matches_fence(self, fence: ClientControlFence) -> bool:
        return fence.matches_hash(self.fence_hash)

    def require_fence(self, fence: ClientControlFence) -> None:
        if not self.matches_fence(fence):
            raise ClientFenceError("stale client control fence rejected")

    def require_controller(self) -> None:
        if self.role is not ClientControllerRole.CONTROLLER:
            raise ClientObserverActionError("observers cannot execute actions or submit receipts")


def ensure_controller_handoff(
    current: ClientControlLease | None,
    *,
    claimant_session_id: ClientSessionId,
) -> None:
    """Observers can only take over through an expired-or-released lease."""

    if current is None or current.is_expired():
        return
    if current.client_session_id != claimant_session_id:
        raise ClientControlLeaseError("another tab holds the active controller lease")
