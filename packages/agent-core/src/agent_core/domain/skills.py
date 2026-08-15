from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, field_validator

MAX_SKILL_COMPONENTS = 32
_SKILL_COMPONENT_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
_SKILL_COMPONENT_DIGEST = re.compile(r"^[a-f0-9]{64}$")


class SkillComponentIdentity(BaseModel):
    """The immutable Skill provenance pinned by a Task grant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    version: str | None = None
    digest: str
    scope: str
    namespace: str
    source: str

    @field_validator("name")
    @classmethod
    def ensure_name(cls, value: str) -> str:
        if not isinstance(value, str) or _SKILL_COMPONENT_NAME.fullmatch(value) is None:
            raise ValueError("skill component identity name is invalid")
        return value

    @field_validator("digest")
    @classmethod
    def ensure_digest(cls, value: str) -> str:
        if not isinstance(value, str) or _SKILL_COMPONENT_DIGEST.fullmatch(value) is None:
            raise ValueError("skill component identity digest must be a lowercase SHA-256")
        return value

    @field_validator("version", "scope", "namespace", "source")
    @classmethod
    def ensure_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized or len(normalized) > 256:
            raise ValueError("skill component identity text is invalid")
        return normalized


def compute_private_skill_package_digest(files: Mapping[str, str]) -> str:
    """Return the canonical digest of an immutable private Skill package."""
    digest = sha256(b"private-skill-package-v1\n")
    for path, content in sorted(files.items()):
        path_bytes = path.encode("utf-8")
        content_bytes = content.encode("utf-8")
        digest.update(len(path_bytes).to_bytes(4, "big"))
        digest.update(path_bytes)
        digest.update(len(content_bytes).to_bytes(8, "big"))
        digest.update(content_bytes)
    return digest.hexdigest()


def normalize_skill_components(value: Sequence[str]) -> tuple[str, ...]:
    if len(value) > MAX_SKILL_COMPONENTS:
        raise ValueError(f"skill_components accepts at most {MAX_SKILL_COMPONENTS} entries")
    normalized: list[str] = []
    seen: set[str] = set()
    for entry in value:
        if not isinstance(entry, str) or not _SKILL_COMPONENT_NAME.fullmatch(entry):
            raise ValueError(
                "skill_components entries must match ^[a-zA-Z][a-zA-Z0-9_-]{0,63}$"
            )
        if entry in seen:
            raise ValueError("skill_components entries must be unique")
        seen.add(entry)
        normalized.append(entry)
    return tuple(sorted(normalized))


def normalize_skill_component_identities(
    value: Sequence[SkillComponentIdentity],
) -> tuple[SkillComponentIdentity, ...]:
    if len(value) > MAX_SKILL_COMPONENTS:
        raise ValueError(
            f"skill component identities accept at most {MAX_SKILL_COMPONENTS} entries"
        )
    normalized: list[SkillComponentIdentity] = []
    names: set[str] = set()
    for identity in value:
        if not isinstance(identity, SkillComponentIdentity):
            raise ValueError(
                "skill component identities must contain SkillComponentIdentity values"
            )
        if identity.name in names:
            raise ValueError("skill component identity names must be unique")
        names.add(identity.name)
        normalized.append(identity)
    return tuple(sorted(normalized, key=lambda identity: identity.name))
