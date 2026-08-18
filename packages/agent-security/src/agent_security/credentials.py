from __future__ import annotations

from dataclasses import dataclass

REDACTED_SECRET = "<redacted>"


@dataclass(frozen=True)
class ScmCredentialSettings:
    """The provider and token reference required by credential policy."""

    provider: str
    token_env: str | None = None


@dataclass(frozen=True)
class ScmCredentialCapability:
    provider: str
    token_env: str | None
    token_value: str | None = None

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("SCM provider must not be blank")
        if self.token_env is not None and not self.token_env.strip():
            raise ValueError("SCM token_env must not be blank when provided")

    def redacted(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "token_env": self.token_env,
            "token_value": REDACTED_SECRET if self.token_value else None,
        }


class ScmCredentialBoundary:
    def capability_from_settings(
        self,
        settings: ScmCredentialSettings,
        *,
        token_value: str | None = None,
    ) -> ScmCredentialCapability:
        if settings.provider == "local-only":
            return ScmCredentialCapability(
                provider=settings.provider,
                token_env=None,
                token_value=None,
            )
        if settings.provider == "github":
            if settings.token_env is None:
                raise ValueError("github SCM provider requires a token environment name")
            return ScmCredentialCapability(
                provider=settings.provider,
                token_env=settings.token_env,
                token_value=token_value,
            )
        raise ValueError(f"unsupported SCM provider: {settings.provider}")

    def settings_snapshot(self, settings: ScmCredentialSettings) -> dict[str, object]:
        return {
            "provider": settings.provider,
            "token_env": settings.token_env,
        }
