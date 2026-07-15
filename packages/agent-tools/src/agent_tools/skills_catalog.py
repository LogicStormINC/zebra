from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

MAX_SKILLS = 200
MAX_SCANNED_DIRECTORIES = 5_000
MAX_SKILL_FILE_BYTES = 32_768
MAX_FRONTMATTER_BYTES = 8_192
MAX_NAME_CHARS = 64
MAX_DESCRIPTION_CHARS = 1_024
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


class SkillCatalogError(ValueError):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    source: str


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


class LocalSkillCatalog:
    """Bounded local catalog adapted from Hermes progressive Skill disclosure."""

    def __init__(self, roots: tuple[str | Path, ...]) -> None:
        self._roots = _validated_roots(roots)

    def list(self, *, limit: int = 100) -> tuple[tuple[SkillMetadata, ...], int, bool]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_SKILLS:
            raise SkillCatalogError("invalid_limit", f"limit must be from 1 to {MAX_SKILLS}")
        entries, ambiguous, truncated = self._discover()
        available = tuple(entry.metadata for entry in entries.values())
        return available[:limit], len(ambiguous), truncated or len(available) > limit

    def read(self, name: str, *, file_path: str = "SKILL.md") -> SkillReadResult:
        normalized_name = _bounded_text(name, "name", MAX_NAME_CHARS)
        entries, ambiguous, _ = self._discover()
        if normalized_name in ambiguous:
            raise SkillCatalogError("ambiguous_skill", "skill name is ambiguous across roots")
        try:
            entry = entries[normalized_name]
        except KeyError as exc:
            raise SkillCatalogError("skill_not_found", "skill is not available") from exc
        relative = _validated_support_path(file_path)
        candidate = entry.root / relative
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise SkillCatalogError("file_not_found", "skill file does not exist") from exc
        if (
            resolved.is_symlink()
            or not resolved.is_file()
            or not resolved.is_relative_to(entry.root)
        ):
            raise SkillCatalogError("path_outside_skill", "skill file escapes its package")
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
            raise SkillCatalogError("invalid_root", f"skill root does not exist: {root}") from exc
        if not canonical.is_dir():
            raise SkillCatalogError("invalid_root", f"skill root is not a directory: {root}")
        if canonical in resolved:
            raise SkillCatalogError("duplicate_root", f"duplicate skill root: {canonical}")
        resolved.append(canonical)
    return tuple(resolved)


def _load_entry(skill_root: Path, configured_root: Path) -> _SkillEntry | None:
    skill_file = skill_root / "SKILL.md"
    if skill_file.is_symlink():
        return None
    try:
        metadata = _frontmatter(_read_prefix_utf8(skill_file))
    except SkillCatalogError:
        return None
    source = skill_root.relative_to(configured_root).as_posix() or "."
    return _SkillEntry(SkillMetadata(metadata[0], metadata[1], source), skill_root.resolve())


def _frontmatter(content: str) -> tuple[str, str]:
    if not content.startswith("---\n"):
        raise SkillCatalogError("invalid_skill", "SKILL.md requires YAML frontmatter")
    end = content.find("\n---", 4)
    if end < 0:
        raise SkillCatalogError("invalid_skill", "SKILL.md frontmatter is not closed")
    lines = content[4:end].splitlines()
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
    return (
        _bounded_text(values.get("name"), "name", MAX_NAME_CHARS),
        _bounded_text(values.get("description"), "description", MAX_DESCRIPTION_CHARS),
    )


def _bounded_text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkillCatalogError("invalid_skill", f"skill {field} must not be blank")
    normalized = " ".join(value.split())
    if len(normalized) > maximum:
        raise SkillCatalogError("invalid_skill", f"skill {field} exceeds {maximum} characters")
    return normalized


def _validated_support_path(value: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise SkillCatalogError("invalid_file_path", "file_path must not be blank")
    normalized = value.strip().replace("\\", "/")
    if len(normalized) > 256:
        raise SkillCatalogError("invalid_file_path", "file_path exceeds 256 characters")
    posix = PurePosixPath(normalized)
    windows = PureWindowsPath(normalized)
    if posix.is_absolute() or windows.is_absolute() or windows.drive or ".." in posix.parts:
        raise SkillCatalogError("invalid_file_path", "file_path must stay within the skill")
    if any(part.startswith(".") for part in posix.parts) or any(
        marker in normalized.lower() for marker in SENSITIVE_PATH_MARKERS
    ):
        raise SkillCatalogError("sensitive_file", "hidden or sensitive skill files are blocked")
    if posix.as_posix() != "SKILL.md" and (
        len(posix.parts) < 2 or posix.parts[0] not in SUPPORT_DIRECTORIES
    ):
        raise SkillCatalogError("unsupported_file", "file must be SKILL.md or a support file")
    return Path(*posix.parts)


def _read_utf8(path: Path) -> tuple[str, int]:
    try:
        size = path.stat().st_size
        if size > MAX_SKILL_FILE_BYTES:
            raise SkillCatalogError("file_too_large", "skill file exceeds 32768 bytes")
        payload = path.read_bytes()
    except OSError as exc:
        raise SkillCatalogError("file_read_failed", "skill file could not be read") from exc
    if b"\x00" in payload:
        raise SkillCatalogError("binary_file", "binary skill files are blocked")
    try:
        return payload.decode("utf-8"), len(payload)
    except UnicodeDecodeError as exc:
        raise SkillCatalogError("invalid_encoding", "skill files must be UTF-8") from exc


def _read_prefix_utf8(path: Path) -> str:
    try:
        with path.open("rb") as stream:
            payload = stream.read(MAX_FRONTMATTER_BYTES + 1)
    except OSError as exc:
        raise SkillCatalogError("file_read_failed", "skill metadata could not be read") from exc
    if len(payload) > MAX_FRONTMATTER_BYTES:
        payload = payload[:MAX_FRONTMATTER_BYTES]
    if b"\x00" in payload:
        raise SkillCatalogError("binary_file", "binary skill files are blocked")
    end = payload.find(b"\n---", 4)
    if end < 0:
        raise SkillCatalogError("invalid_skill", "SKILL.md frontmatter exceeds its bound")
    payload = payload[: end + 4]
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillCatalogError("invalid_encoding", "skill files must be UTF-8") from exc
