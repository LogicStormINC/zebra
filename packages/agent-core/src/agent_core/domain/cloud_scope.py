from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_core.domain.session_history import normalize_history_session_ids

MAX_AUTHORITY_ISSUER_LENGTH = 2_048
MAX_NAMESPACE_ID_LENGTH = 255


class OpaqueAuthorityScope(BaseModel):
    """Trusted external authority scope for cloud read composition.

    ``authority_issuer`` and ``namespace_id`` are opaque identity components.
    Their mapping to an internal deployment namespace is intentionally owned by
    trusted composition rather than this Core value object.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    authority_issuer: str = Field(max_length=MAX_AUTHORITY_ISSUER_LENGTH)
    namespace_id: str = Field(max_length=MAX_NAMESPACE_ID_LENGTH)
    allowed_session_ids: tuple[str, ...] | None = None

    @field_validator("authority_issuer", "namespace_id")
    @classmethod
    def require_trimmed_opaque_value(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("opaque authority scope values must be non-blank and trimmed")
        return value

    @field_validator("allowed_session_ids", mode="before")
    @classmethod
    def normalize_allowed_session_ids(
        cls, value: tuple[str, ...] | list[str] | None
    ) -> tuple[str, ...] | None:
        if value is None:
            return None
        if isinstance(value, str):
            raise ValueError("allowed_session_ids must be a sequence of UUID strings")
        try:
            return normalize_history_session_ids(value)
        except ValueError as exc:
            raise ValueError(f"invalid allowed_session_ids: {exc}") from exc

    @property
    def scope_key(self) -> tuple[str, str]:
        """Return the durable external identity without deriving storage keys."""

        return self.authority_issuer, self.namespace_id

    @property
    def is_full_namespace(self) -> bool:
        return self.allowed_session_ids is None

    @property
    def is_deny_all(self) -> bool:
        return self.allowed_session_ids == ()

    def allows_session(self, session_id: str | UUID) -> bool:
        """Return whether a canonical Session UUID is in this read scope."""

        if self.allowed_session_ids is None:
            return True
        try:
            canonical_session_id = str(UUID(str(session_id).strip()))
        except (AttributeError, ValueError) as exc:
            raise ValueError("session_id must be a UUID") from exc
        return canonical_session_id in self.allowed_session_ids
