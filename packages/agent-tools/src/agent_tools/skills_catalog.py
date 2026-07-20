from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType

MAX_SKILLS = 200
MAX_SCANNED_DIRECTORIES = 5_000
MAX_SKILL_FILE_BYTES = 32_768
MAX_FRONTMATTER_BYTES = 8_192
MAX_NAME_CHARS = 64
MAX_DESCRIPTION_CHARS = 1_024
MAX_VERSION_CHARS = 64
MAX_LICENSE_CHARS = 128
MAX_COMPATIBILITY_ENTRIES = 8
MAX_METADATA_ENTRIES = 32
MAX_METADATA_KEY_CHARS = 64
MAX_METADATA_VALUE_CHARS = 256
EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".github",
        ".hub",
        ".archive",
        ".venv",
        "venv",
        "node_modules",
        "site-packages",
        "__pycache__",
        ".tox",
        ".nox",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
)
SUPPORT_DIRECTORIES = frozenset({"references", "templates", "assets", "scripts"})
SENSITIVE_PATH_MARKERS = (".env", "credential", "id_rsa", "private_key", "secret", "token")
_STANDARD_FRONTMATTER_FIELDS = frozenset(
    {"name", "description", "version", "license", "compatibility"}
)


class SkillCatalogReason(StrEnum):
    """Stable reason codes for :class:`SkillCatalogError`.

    Wire values are frozen; existing callers that compare ``.reason`` to a
    literal string keep working. ``INVALID_ARGUMENTS`` is raised from the skill
    tool layer (``skills.py``) and centralized here as the authoritative name.
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


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    source: str
    version: str | None = None
    license: str | None = None
    compatibility: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    digest: str | None = None


@dataclass(frozen=True)
class SkillReadResult:
    metadata: SkillMetadata
    file_path: str
    content: str
    byte_count: int


@dataclass(frozen=True)
class _SkillEntry:
    metadata: SkillMetadata
    root: Path


@dataclass(frozen=True)
class _ParsedFrontmatter:
    name: str
    description: str
    version: str | None = None
    license: str | None = None
    compatibility: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))


class LocalSkillCatalog:
    """Bounded local catalog adapted from Hermes progressive Skill disclosure."""

    def __init__(self, roots: tuple[str | Path, ...]) -> None:
        self._roots = _validated_roots(roots)

    def list(self, *, limit: int = 100) -> tuple[tuple[SkillMetadata, ...], int, bool]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_SKILLS:
            raise SkillCatalogError(
                SkillCatalogReason.INVALID_LIMIT, f"limit must be from 1 to {MAX_SKILLS}"
            )
        entries, ambiguous, truncated = self._discover()
        available = tuple(entry.metadata for entry in entries.values())
        return available[:limit], len(ambiguous), truncated or len(available) > limit

    def read(self, name: str, *, file_path: str = "SKILL.md") -> SkillReadResult:
        normalized_name = _bounded_text(name, "name", MAX_NAME_CHARS)
        entries, ambiguous, _ = self._discover()
        if normalized_name in ambiguous:
            raise SkillCatalogError(
                SkillCatalogReason.AMBIGUOUS_SKILL, "skill name is ambiguous across roots"
            )
        try:
            entry = entries[normalized_name]
        except KeyError as exc:
            raise SkillCatalogError(
                SkillCatalogReason.SKILL_NOT_FOUND, "skill is not available"
            ) from exc
        relative = _validated_support_path(file_path)
        candidate = entry.root / relative
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise SkillCatalogError(
                SkillCatalogReason.FILE_NOT_FOUND, "skill file does not exist"
            ) from exc
        if (
            resolved.is_symlink()
            or not resolved.is_file()
            or not resolved.is_relative_to(entry.root)
        ):
            raise SkillCatalogError(
                SkillCatalogReason.PATH_OUTSIDE_SKILL, "skill file escapes its package"
            )
        content, byte_count = _read_utf8(resolved)
        return SkillReadResult(entry.metadata, relative.as_posix(), content, byte_count)

    def _discover(self) -> tuple[dict[str, _SkillEntry], frozenset[str], bool]:
        entries: dict[str, _SkillEntry] = {}
        ambiguous: set[str] = set()
        scanned = 0
        truncated = False
        for configured_root in self._roots:
            for directory, directory_names, filenames in os.walk(
                configured_root, followlinks=False
            ):
                scanned += 1
                if scanned > MAX_SCANNED_DIRECTORIES:
                    truncated = True
                    break
                current = Path(directory)
                directory_names[:] = sorted(
                    name
                    for name in directory_names
                    if name not in EXCLUDED_DIRECTORIES
                    and not name.startswith(".")
                    and not (current / name).is_symlink()
                )
                if "SKILL.md" not in filenames:
                    continue
                directory_names[:] = [
                    name for name in directory_names if name not in SUPPORT_DIRECTORIES
                ]
                entry = _load_entry(current, configured_root)
                if entry is None:
                    continue
                name = entry.metadata.name
                if name in entries:
                    entries.pop(name)
                    ambiguous.add(name)
                elif name not in ambiguous and len(entries) + len(ambiguous) < MAX_SKILLS:
                    entries[name] = entry
                elif name not in ambiguous:
                    truncated = True
            if truncated:
                continue
        return dict(sorted(entries.items())), frozenset(ambiguous), truncated


def _validated_roots(roots: tuple[str | Path, ...]) -> tuple[Path, ...]:
    resolved: list[Path] = []
    for raw_root in roots:
        root = Path(raw_root).expanduser()
        try:
            canonical = root.resolve(strict=True)
        except OSError as exc:
            raise SkillCatalogError(
                SkillCatalogReason.INVALID_ROOT, f"skill root does not exist: {root}"
            ) from exc
        if not canonical.is_dir():
            raise SkillCatalogError(
                SkillCatalogReason.INVALID_ROOT, f"skill root is not a directory: {root}"
            )
        if canonical in resolved:
            raise SkillCatalogError(
                SkillCatalogReason.DUPLICATE_ROOT, f"duplicate skill root: {canonical}"
            )
        resolved.append(canonical)
    return tuple(resolved)


def _load_entry(skill_root: Path, configured_root: Path) -> _SkillEntry | None:
    skill_file = skill_root / "SKILL.md"
    if skill_file.is_symlink():
        return None
    try:
        parsed = _frontmatter(_read_prefix_utf8(skill_file))
    except SkillCatalogError:
        return None
    source = skill_root.relative_to(configured_root).as_posix() or "."
    return _SkillEntry(
        SkillMetadata(
            name=parsed.name,
            description=parsed.description,
            source=source,
            version=parsed.version,
            license=parsed.license,
            compatibility=parsed.compatibility,
            metadata=parsed.metadata,
        ),
        skill_root.resolve(),
    )


def _frontmatter(content: str) -> _ParsedFrontmatter:
    if not content.startswith("---\n"):
        raise SkillCatalogError(
            SkillCatalogReason.INVALID_SKILL, "SKILL.md requires YAML frontmatter"
        )
    end = content.find("\n---", 4)
    if end < 0:
        raise SkillCatalogError(
            SkillCatalogReason.INVALID_SKILL, "SKILL.md frontmatter is not closed"
        )
    values = _parse_frontmatter_mapping(content[4:end])
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


def _validated_support_path(value: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise SkillCatalogError(
            SkillCatalogReason.INVALID_FILE_PATH, "file_path must not be blank"
        )
    normalized = value.strip().replace("\\", "/")
    if len(normalized) > 256:
        raise SkillCatalogError(
            SkillCatalogReason.INVALID_FILE_PATH, "file_path exceeds 256 characters"
        )
    posix = PurePosixPath(normalized)
    windows = PureWindowsPath(normalized)
    if posix.is_absolute() or windows.is_absolute() or windows.drive or ".." in posix.parts:
        raise SkillCatalogError(
            SkillCatalogReason.INVALID_FILE_PATH, "file_path must stay within the skill"
        )
    if any(part.startswith(".") for part in posix.parts) or any(
        marker in normalized.lower() for marker in SENSITIVE_PATH_MARKERS
    ):
        raise SkillCatalogError(
            SkillCatalogReason.SENSITIVE_FILE, "hidden or sensitive skill files are blocked"
        )
    if posix.as_posix() != "SKILL.md" and (
        len(posix.parts) < 2 or posix.parts[0] not in SUPPORT_DIRECTORIES
    ):
        raise SkillCatalogError(
            SkillCatalogReason.UNSUPPORTED_FILE, "file must be SKILL.md or a support file"
        )
    return Path(*posix.parts)


def _read_utf8(path: Path) -> tuple[str, int]:
    try:
        size = path.stat().st_size
        if size > MAX_SKILL_FILE_BYTES:
            raise SkillCatalogError(
                SkillCatalogReason.FILE_TOO_LARGE, "skill file exceeds 32768 bytes"
            )
        payload = path.read_bytes()
    except OSError as exc:
        raise SkillCatalogError(
            SkillCatalogReason.FILE_READ_FAILED, "skill file could not be read"
        ) from exc
    if b"\x00" in payload:
        raise SkillCatalogError(SkillCatalogReason.BINARY_FILE, "binary skill files are blocked")
    try:
        return payload.decode("utf-8"), len(payload)
    except UnicodeDecodeError as exc:
        raise SkillCatalogError(
            SkillCatalogReason.INVALID_ENCODING, "skill files must be UTF-8"
        ) from exc


def _read_prefix_utf8(path: Path) -> str:
    try:
        with path.open("rb") as stream:
            payload = stream.read(MAX_FRONTMATTER_BYTES + 1)
    except OSError as exc:
        raise SkillCatalogError(
            SkillCatalogReason.FILE_READ_FAILED, "skill metadata could not be read"
        ) from exc
    if len(payload) > MAX_FRONTMATTER_BYTES:
        payload = payload[:MAX_FRONTMATTER_BYTES]
    if b"\x00" in payload:
        raise SkillCatalogError(SkillCatalogReason.BINARY_FILE, "binary skill files are blocked")
    end = payload.find(b"\n---", 4)
    if end < 0:
        raise SkillCatalogError(
            SkillCatalogReason.INVALID_SKILL, "SKILL.md frontmatter exceeds its bound"
        )
    payload = payload[: end + 4]
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillCatalogError(
            SkillCatalogReason.INVALID_ENCODING, "skill files must be UTF-8"
        ) from exc
