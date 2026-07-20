from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType

from agent_tools.skills_scope import (
    MAX_COMPATIBILITY_ENTRIES as MAX_COMPATIBILITY_ENTRIES,
)
from agent_tools.skills_scope import (
    MAX_METADATA_ENTRIES as MAX_METADATA_ENTRIES,
)
from agent_tools.skills_scope import (
    MAX_NAME_CHARS as MAX_NAME_CHARS,
)
from agent_tools.skills_scope import (
    ScopedSkillRoot,
    SkillScope,
    _bounded_text,
    compute_skill_digest,
    default_namespace,
    normalize_scoped_roots,
    parse_frontmatter,
    scope_priority,
    split_frontmatter,
)
from agent_tools.skills_scope import SkillCatalogError as SkillCatalogError
from agent_tools.skills_scope import SkillCatalogReason as SkillCatalogReason

MAX_SKILLS = 200
MAX_SCANNED_DIRECTORIES = 5_000
MAX_SKILL_FILE_BYTES = 32_768
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

__all__ = [
    "MAX_COMPATIBILITY_ENTRIES",
    "MAX_METADATA_ENTRIES",
    "MAX_NAME_CHARS",
    "MAX_SKILLS",
    "LocalSkillCatalog",
    "SkillCatalogError",
    "SkillCatalogReason",
    "SkillMetadata",
    "SkillReadResult",
    "SkillScope",
    "ScopedSkillRoot",
]


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
    scope: SkillScope = SkillScope.USER
    namespace: str | None = None


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
    scope: SkillScope
    namespace: str


class LocalSkillCatalog:
    """Bounded local catalog with scope-ordered, digest-pinned skill discovery."""

    def __init__(self, roots: tuple[str | Path | ScopedSkillRoot, ...]) -> None:
        self._roots = normalize_scoped_roots(roots)

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
        for scoped_root in self._roots:
            for directory, directory_names, filenames in os.walk(
                scoped_root.root, followlinks=False
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
                entry = _load_entry(current, scoped_root)
                if entry is None:
                    continue
                name = entry.metadata.name
                if name in ambiguous:
                    continue
                existing = entries.get(name)
                if existing is None:
                    if len(entries) + len(ambiguous) < MAX_SKILLS:
                        entries[name] = entry
                    else:
                        truncated = True
                    continue
                if existing.scope == entry.scope:
                    entries.pop(name)
                    ambiguous.add(name)
                elif scope_priority(entry.scope) < scope_priority(existing.scope):
                    entries[name] = entry
            if truncated:
                continue
        return dict(sorted(entries.items())), frozenset(ambiguous), truncated


def _load_entry(skill_root: Path, scoped: ScopedSkillRoot) -> _SkillEntry | None:
    skill_file = skill_root / "SKILL.md"
    if skill_file.is_symlink():
        return None
    try:
        raw_bytes = skill_file.read_bytes()
    except OSError:
        return None
    try:
        frontmatter_text, body_bytes = split_frontmatter(raw_bytes)
        parsed = parse_frontmatter(frontmatter_text)
    except SkillCatalogError:
        return None
    source = skill_root.relative_to(Path(scoped.root)).as_posix() or "."
    namespace = scoped.namespace or default_namespace(scoped.scope)
    digest = compute_skill_digest(frontmatter_text.encode("utf-8"), body_bytes)
    return _SkillEntry(
        SkillMetadata(
            name=parsed.name,
            description=parsed.description,
            source=source,
            version=parsed.version,
            license=parsed.license,
            compatibility=parsed.compatibility,
            metadata=parsed.metadata,
            digest=digest,
            scope=scoped.scope,
            namespace=namespace,
        ),
        skill_root.resolve(),
        scoped.scope,
        namespace,
    )


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
