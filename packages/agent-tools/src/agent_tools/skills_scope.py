from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

MAX_FRONTMATTER_BYTES = 8_192
MAX_NAME_CHARS = 64
MAX_DESCRIPTION_CHARS = 1_024
MAX_VERSION_CHARS = 64
MAX_LICENSE_CHARS = 128
MAX_COMPATIBILITY_ENTRIES = 8
MAX_METADATA_ENTRIES = 32
MAX_METADATA_KEY_CHARS = 64
MAX_METADATA_VALUE_CHARS = 256
MAX_NAMESPACE_CHARS = 32


class SkillCatalogReason(StrEnum):
    """Stable reason codes for :class:`SkillCatalogError`.

    Wire values are frozen; existing callers comparing ``.reason`` to a literal
    string keep working. ``INVALID_ARGUMENTS`` is raised from the skill tool
    layer and centralized here as the authoritative name.
    """

    INVALID_LIMIT = "invalid_limit"
    INVALID_ROOT = "invalid_root"
    DUPLICATE_ROOT = "duplicate_root"
    INVALID_SKILL = "invalid_skill"
    SKILL_NOT_FOUND = "skill_not_found"
    AMBIGUOUS_SKILL = "ambiguous_skill"
    FILE_NOT_FOUND = "file_not_found"
    PATH_OUTSIDE_SKILL = "path_outside_skill"
    FILE_TOO_LARGE = "file_too_large"
    BINARY_FILE = "binary_file"
    INVALID_ENCODING = "invalid_encoding"
    INVALID_FILE_PATH = "invalid_file_path"
    SENSITIVE_FILE = "sensitive_file"
    UNSUPPORTED_FILE = "unsupported_file"
    FILE_READ_FAILED = "file_read_failed"
    INVALID_ARGUMENTS = "invalid_arguments"


class SkillCatalogError(ValueError):
    def __init__(self, reason: str | SkillCatalogReason, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason.value if isinstance(reason, SkillCatalogReason) else reason


class SkillScope(StrEnum):
    """Skill provenance scope. Lower :func:`scope_priority` wins on collisions."""

    SYSTEM = "system"
    ADMIN = "admin"
    USER = "user"
    REPO = "repo"


_SCOPE_PRIORITY: dict[SkillScope, int] = {
    SkillScope.SYSTEM: 0,
    SkillScope.ADMIN: 1,
    SkillScope.USER: 2,
    SkillScope.REPO: 3,
}


def scope_priority(scope: SkillScope) -> int:
    return _SCOPE_PRIORITY[scope]


def default_namespace(scope: SkillScope) -> str:
    return scope.value


@dataclass(frozen=True)
class ScopedSkillRoot:
    scope: SkillScope
    root: str
    namespace: str | None = None


def compute_skill_digest(manifest_bytes: bytes, body_bytes: bytes) -> str:
    """SHA-256 of canonical (manifest || body), mirroring ``runtime_spec_digest``."""
    digest = hashlib.sha256()
    digest.update(b"skill-manifest-v1\n")
    digest.update(manifest_bytes)
    digest.update(b"\nskill-body-v1\n")
    digest.update(body_bytes)
    return digest.hexdigest()


@dataclass(frozen=True)
class _ParsedFrontmatter:
    name: str
    description: str
    version: str | None = None
    license: str | None = None
    compatibility: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))


def split_frontmatter(raw_bytes: bytes) -> tuple[str, bytes]:
    """Split a SKILL.md byte payload into ``(frontmatter_text, body_bytes)``.

    Enforces the frontmatter bound and rejects binary/non-UTF-8 payloads. The
    returned frontmatter text includes the opening and closing ``---`` fences.
    """
    if b"\x00" in raw_bytes:
        raise SkillCatalogError(SkillCatalogReason.BINARY_FILE, "binary skill files are blocked")
    try:
        content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillCatalogError(
            SkillCatalogReason.INVALID_ENCODING, "skill files must be UTF-8"
        ) from exc
    if not content.startswith("---\n"):
        raise SkillCatalogError(
            SkillCatalogReason.INVALID_SKILL, "SKILL.md requires YAML frontmatter"
        )
    end = content.find("\n---", 4)
    if end < 0:
        raise SkillCatalogError(
            SkillCatalogReason.INVALID_SKILL, "SKILL.md frontmatter is not closed"
        )
    frontmatter_text = content[: end + 4]
    if len(frontmatter_text.encode("utf-8")) > MAX_FRONTMATTER_BYTES:
        raise SkillCatalogError(
            SkillCatalogReason.INVALID_SKILL, "SKILL.md frontmatter exceeds its bound"
        )
    body_offset = len(frontmatter_text.encode("utf-8"))
    return frontmatter_text, raw_bytes[body_offset:]


def parse_frontmatter(frontmatter_text: str) -> _ParsedFrontmatter:
    values = _parse_frontmatter_mapping(frontmatter_text[4:])
    name = _bounded_text(values.pop("name", None), "name", MAX_NAME_CHARS)
    description = _bounded_text(
        values.pop("description", None), "description", MAX_DESCRIPTION_CHARS
    )
    version = _optional_bounded_text(values.pop("version", None), "version", MAX_VERSION_CHARS)
    license_value = _optional_bounded_text(
        values.pop("license", None), "license", MAX_LICENSE_CHARS
    )
    compatibility = _parse_compatibility(values.pop("compatibility", None))
    metadata = _parse_metadata_map(values)
    return _ParsedFrontmatter(
        name=name,
        description=description,
        version=version,
        license=license_value,
        compatibility=compatibility,
        metadata=metadata,
    )


def _parse_frontmatter_mapping(body: str) -> dict[str, str]:
    lines = body.splitlines()
    values: dict[str, str] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if ":" not in line or line[:1].isspace():
            index += 1
            continue
        key, raw_value = line.split(":", 1)
        value = raw_value.strip()
        if value in {"|", "|-", ">", ">-"}:
            block: list[str] = []
            index += 1
            while index < len(lines) and (not lines[index] or lines[index][:1].isspace()):
                block.append(lines[index].strip())
                index += 1
            values[key.strip()] = " ".join(part for part in block if part)
            continue
        values[key.strip()] = value.strip("\"'")
        index += 1
    return values


def _bounded_text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkillCatalogError(
            SkillCatalogReason.INVALID_SKILL, f"skill {field} must not be blank"
        )
    normalized = " ".join(value.split())
    if len(normalized) > maximum:
        raise SkillCatalogError(
            SkillCatalogReason.INVALID_SKILL, f"skill {field} exceeds {maximum} characters"
        )
    return normalized


def _optional_bounded_text(value: object, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    return _bounded_text(value, field, maximum)


def _parse_compatibility(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, str):
        raise SkillCatalogError(
            SkillCatalogReason.INVALID_SKILL, "skill compatibility must be text"
        )
    normalized: list[str] = []
    for token in value.split():
        cleaned = " ".join(token.split())
        if len(cleaned) > MAX_VERSION_CHARS:
            raise SkillCatalogError(
                SkillCatalogReason.INVALID_SKILL, "skill compatibility entry is too long"
            )
        normalized.append(cleaned)
    if len(normalized) > MAX_COMPATIBILITY_ENTRIES:
        raise SkillCatalogError(
            SkillCatalogReason.INVALID_SKILL,
            f"skill compatibility exceeds {MAX_COMPATIBILITY_ENTRIES} entries",
        )
    return tuple(normalized)


def _parse_metadata_map(values: dict[str, str]) -> Mapping[str, str]:
    if len(values) > MAX_METADATA_ENTRIES:
        raise SkillCatalogError(
            SkillCatalogReason.INVALID_SKILL,
            f"skill metadata exceeds {MAX_METADATA_ENTRIES} entries",
        )
    metadata: dict[str, str] = {}
    for key, raw_value in values.items():
        cleaned_key = " ".join(key.split())
        if not cleaned_key or len(cleaned_key) > MAX_METADATA_KEY_CHARS:
            raise SkillCatalogError(
                SkillCatalogReason.INVALID_SKILL, "skill metadata key is invalid"
            )
        metadata[cleaned_key] = _bounded_metadata_value(raw_value)
    return MappingProxyType(metadata)


def _bounded_metadata_value(value: object) -> str:
    if not isinstance(value, str):
        raise SkillCatalogError(
            SkillCatalogReason.INVALID_SKILL, "skill metadata value must be text"
        )
    cleaned = " ".join(value.split())
    if not cleaned:
        raise SkillCatalogError(
            SkillCatalogReason.INVALID_SKILL, "skill metadata value must not be blank"
        )
    if len(cleaned) > MAX_METADATA_VALUE_CHARS:
        raise SkillCatalogError(
            SkillCatalogReason.INVALID_SKILL, "skill metadata value is too long"
        )
    return cleaned


def normalize_scoped_roots(
    roots: Sequence[str | Path | ScopedSkillRoot],
) -> tuple[ScopedSkillRoot, ...]:
    """Validate, dedupe, and scope-order skill roots.

    Bare ``str``/``Path`` roots are treated as :attr:`SkillScope.USER` for
    backward compatibility. Roots are returned ordered by ascending scope
    priority so discovery scans higher-trust scopes first.
    """
    resolved: list[ScopedSkillRoot] = []
    seen: set[Path] = set()
    for raw in roots:
        if isinstance(raw, ScopedSkillRoot):
            scope = raw.scope
            namespace = raw.namespace
            raw_path = raw.root
        elif isinstance(raw, str | Path):
            scope = SkillScope.USER
            namespace = None
            raw_path = str(raw)
        else:
            raise SkillCatalogError(
                SkillCatalogReason.INVALID_ROOT, f"invalid skill root: {raw!r}"
            )
        path = Path(raw_path).expanduser()
        try:
            canonical = path.resolve(strict=True)
        except OSError as exc:
            raise SkillCatalogError(
                SkillCatalogReason.INVALID_ROOT, f"skill root does not exist: {path}"
            ) from exc
        if not canonical.is_dir():
            raise SkillCatalogError(
                SkillCatalogReason.INVALID_ROOT, f"skill root is not a directory: {path}"
            )
        if canonical in seen:
            raise SkillCatalogError(
                SkillCatalogReason.DUPLICATE_ROOT, f"duplicate skill root: {canonical}"
            )
        seen.add(canonical)
        resolved.append(ScopedSkillRoot(scope=scope, root=str(canonical), namespace=namespace))
    resolved.sort(key=lambda item: scope_priority(item.scope))
    return tuple(resolved)
