"""Plugin manifest domain models and bounded lifecycle (EXT-PLUGIN-01, ADR-014).

The manifest is install-preview metadata only: requested capabilities never
form a Task grant. The lifecycle is a five-layer state machine where no layer
derives the next; durable decisions remain in the Session Event Store or the
operator-owned enablement state, never inside the plugin package.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from hashlib import sha256
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

MANIFEST_VERSION = "0.1"

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
_NAMESPACE_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_TOKEN_ENV_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


class PluginScope(StrEnum):
    SYSTEM = "system"
    ADMIN = "admin"
    USER = "user"
    REPO = "repo"


class PluginEntryKind(StrEnum):
    SKILL_BUNDLE = "skill-bundle"
    MCP_STDIO = "mcp-stdio"
    MCP_HTTP = "mcp-http"
    HOOK = "hook"


class PluginLifecycleState(StrEnum):
    """ADR-014 five-layer machine; transitions never derive automatically."""

    AVAILABLE = "available"
    INSTALLED = "installed"
    ENABLED = "enabled"
    GRANTED = "granted"
    APPROVED = "approved"


_ALLOWED_TRANSITIONS = {
    PluginLifecycleState.AVAILABLE: {PluginLifecycleState.INSTALLED},
    PluginLifecycleState.INSTALLED: {
        PluginLifecycleState.ENABLED,
        PluginLifecycleState.AVAILABLE,
    },
    PluginLifecycleState.ENABLED: {
        PluginLifecycleState.GRANTED,
        PluginLifecycleState.INSTALLED,
    },
    PluginLifecycleState.GRANTED: {
        PluginLifecycleState.APPROVED,
        PluginLifecycleState.ENABLED,
    },
    PluginLifecycleState.APPROVED: {PluginLifecycleState.GRANTED},
}


class PluginTransitionError(ValueError):
    """Raised when a lifecycle transition is not allowed."""


class PluginRequestedCapabilities(BaseModel):
    """Install-preview only; never a Task grant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tools: tuple[str, ...] = ()
    network: tuple[str, ...] = ()
    elicitation: bool = False


class PluginProvenance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    digest: str
    signature: str | None = None
    source_url: str | None = None

    @field_validator("digest")
    @classmethod
    def require_digest(cls, value: str) -> str:
        stripped = value.strip()
        if not _DIGEST_PATTERN.fullmatch(stripped):
            raise ValueError("provenance digest must be sha256:<64 lowercase hex>")
        return stripped


class PluginEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: PluginEntryKind
    skill_root: str | None = None
    command: str | None = None
    args: tuple[str, ...] = ()
    url: str | None = None
    bearer_token_env: str | None = None

    @model_validator(mode="after")
    def validate_entry_shape(self) -> Self:
        if self.kind is PluginEntryKind.SKILL_BUNDLE:
            if not self.skill_root or not self.skill_root.strip():
                raise ValueError("skill-bundle entries require skill_root")
        elif self.kind is PluginEntryKind.MCP_STDIO:
            if not self.command or not self.command.strip():
                raise ValueError("mcp-stdio entries require command")
            if not self.command.startswith("/"):
                raise ValueError("mcp-stdio command must be an absolute path")
        elif self.kind is PluginEntryKind.MCP_HTTP:
            if not self.url or not self.url.startswith("https://"):
                raise ValueError("mcp-http entries require an https:// url")
            if self.bearer_token_env is not None and not _TOKEN_ENV_PATTERN.fullmatch(
                self.bearer_token_env
            ):
                raise ValueError("bearer_token_env must be an env variable name")
        elif self.kind is PluginEntryKind.HOOK:
            if not self.command or not self.command.startswith("/"):
                raise ValueError("hook entries require an absolute command path")
        return self


class PluginManifest(BaseModel):
    """One signed package descriptor; identity includes publisher and digest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_version: str = MANIFEST_VERSION
    id: str
    version: str
    scope: PluginScope
    entry: PluginEntry
    publisher: str | None = None
    namespace: str | None = None
    license: str | None = None
    requested_capabilities: PluginRequestedCapabilities = (
        PluginRequestedCapabilities()
    )
    provenance: PluginProvenance | None = None

    @field_validator("manifest_version")
    @classmethod
    def require_version(cls, value: str) -> str:
        if value != MANIFEST_VERSION:
            raise ValueError(f"manifest_version must be {MANIFEST_VERSION}")
        return value

    @field_validator("id")
    @classmethod
    def require_id(cls, value: str) -> str:
        if not _ID_PATTERN.fullmatch(value):
            raise ValueError("plugin id must be lowercase kebab-case (3-64 chars)")
        return value

    @field_validator("version")
    @classmethod
    def require_semver(cls, value: str) -> str:
        if not _VERSION_PATTERN.fullmatch(value):
            raise ValueError("plugin version must be plain semver x.y.z")
        return value

    @field_validator("namespace")
    @classmethod
    def require_namespace(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _NAMESPACE_PATTERN.fullmatch(value):
            raise ValueError("plugin namespace must be a lowercase identifier")
        return value

    @property
    def effective_namespace(self) -> str:
        return self.namespace or self.scope.value

    @property
    def component_identity(self) -> str:
        publisher = self.publisher or "unpublished"
        digest = self.provenance.digest.removeprefix("sha256:") if self.provenance else ""
        return f"{publisher}/{self.id}@{self.version}#{digest[:16]}"

    def canonical_json(self) -> str:
        payload = json.loads(self.model_dump_json(exclude_none=True))
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def content_digest(self) -> str:
        return "sha256:" + sha256(self.canonical_json().encode()).hexdigest()

    @classmethod
    def validate_document(cls, document: object) -> Self:
        if not isinstance(document, dict):
            raise ValueError("plugin manifest must be a JSON object")
        return cls.model_validate(document)


class PluginInstallRecord(BaseModel):
    """Immutable install decision pinning an exact content digest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest: PluginManifest
    installed_digest: str
    installed_at: str
    operator: str

    @model_validator(mode="after")
    def digest_pinned(self) -> Self:
        expected = self.manifest.content_digest()
        if self.installed_digest != expected:
            raise ValueError(
                "install record digest does not match the manifest content"
            )
        return self


def transition_plugin_state(
    current: PluginLifecycleState,
    target: PluginLifecycleState,
) -> PluginLifecycleState:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise PluginTransitionError(
            f"plugin lifecycle cannot transition {current.value} -> {target.value}"
        )
    return target
