from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, cast

from agent_core.domain.skills import (
    SkillComponentIdentity,
    compute_private_skill_package_digest,
    normalize_skill_component_identities,
)

from agent_tools.skills_scope import (
    MAX_COMPATIBILITY_ENTRIES,
    MAX_METADATA_ENTRIES,
    MAX_NAME_CHARS,
    SUPPORT_DIRECTORIES,
    ScopedSkillRoot,
    SkillCatalogError,
    SkillCatalogReason,
    SkillScope,
    _bounded_text,
    compute_skill_digest,
    default_namespace,
    normalize_scoped_roots,
    parse_frontmatter,
    read_skill_package,
    scope_priority,
    split_frontmatter,
    validate_skill_file_path,
)
from agent_tools.skills_scope import (
    read_skill_file as _read_utf8,
)

MAX_SKILLS = 200
MAX_SCANNED_DIRECTORIES = 5_000
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

__all__ = [
    "MAX_COMPATIBILITY_ENTRIES",
    "MAX_METADATA_ENTRIES",
    "MAX_NAME_CHARS",
    "MAX_SKILLS",
    "LocalSkillCatalog",
    "SkillCatalogError",
    "SkillCatalogReason",
    "SkillEnablementState",
    "SkillMetadata",
    "SkillReadResult",
    "SkillScope",
    "ScopedSkillRoot",
]


class SkillEnablementState(Protocol):
    """Read-only legacy disable view; stores may expose lifecycle helpers."""

    def disabled_components(self) -> frozenset[tuple[str, str]]: ...


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
    owner: str | None = None

    def component_identity(self) -> SkillComponentIdentity:
        if self.digest is None or self.namespace is None:
            raise ValueError("skill metadata is missing an immutable component identity")
        return SkillComponentIdentity(
            name=self.name,
            version=self.version,
            digest=self.digest,
            scope=self.scope.value,
            namespace=self.namespace,
            source=self.source,
        )


@dataclass(frozen=True)
class SkillReadResult:
    metadata: SkillMetadata
    file_path: str
    content: str
    byte_count: int


@dataclass(frozen=True)
class _SkillEntry:
    metadata: SkillMetadata
    root: Path | None
    owner: str | None
    files: Mapping[str, str] | None = None


class LocalSkillCatalog:
    """Bounded local catalog with scope-ordered, digest-pinned skill discovery."""

    def __init__(
        self,
        roots: tuple[str | Path | ScopedSkillRoot, ...],
        *,
        skills_state: SkillEnablementState | None = None,
        granted_component_identities: tuple[SkillComponentIdentity, ...] | None = None,
        inventory_only: bool = False,
    ) -> None:
        self._roots = normalize_scoped_roots(roots)
        private_owners = {root.owner for root in self._roots if root.owner is not None}
        if len(private_owners) > 1:
            raise SkillCatalogError(
                SkillCatalogReason.INVALID_ROOT,
                "a catalog may serve only one private Skill owner",
            )
        self._private_owner = next(iter(private_owners), None)
        self._skills_state = skills_state
        self._inventory_only = inventory_only
        self._granted_component_identities = (
            None
            if granted_component_identities is None
            else normalize_skill_component_identities(granted_component_identities)
        )

    def list(self, *, limit: int = 100) -> tuple[tuple[SkillMetadata, ...], int, bool]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_SKILLS:
            raise SkillCatalogError(
                SkillCatalogReason.INVALID_LIMIT, f"limit must be from 1 to {MAX_SKILLS}"
            )
        entries, ambiguous, truncated = self._discover()
        available_entries = self._available_entries(entries)
        if self._granted_component_identities is None:
            available_entries = {
                name: entry for name, entry in available_entries.items() if name not in ambiguous
            }
        available = tuple(entry.metadata for entry in available_entries.values())
        return available[:limit], len(ambiguous), truncated or len(available) > limit

    def read(self, name: str, *, file_path: str = "SKILL.md") -> SkillReadResult:
        normalized_name = _bounded_text(name, "name", MAX_NAME_CHARS)
        entries, ambiguous, _ = self._discover()
        if self._granted_component_identities is None and normalized_name in ambiguous:
            raise SkillCatalogError(
                SkillCatalogReason.AMBIGUOUS_SKILL, "skill name is ambiguous across roots"
            )
        entries = self._available_entries(entries)
        if normalized_name in ambiguous and normalized_name not in entries:
            raise SkillCatalogError(
                SkillCatalogReason.AMBIGUOUS_SKILL, "skill name is ambiguous across roots"
            )
        try:
            entry = entries[normalized_name]
        except KeyError as exc:
            raise SkillCatalogError(
                SkillCatalogReason.SKILL_NOT_FOUND, "skill is not available"
            ) from exc
        relative = validate_skill_file_path(file_path)
        files = entry.files
        if files is None:
            assert entry.root is not None
            _validate_live_file(entry.root, relative)
            _read_utf8(entry.root / "SKILL.md")
            files = read_skill_package(entry.root)
        try:
            content = files[relative.as_posix()]
        except KeyError as exc:
            raise SkillCatalogError(
                SkillCatalogReason.FILE_NOT_FOUND, "skill file does not exist"
            ) from exc
        _ensure_entry_digest(entry, files)
        byte_count = len(content.encode("utf-8"))
        return SkillReadResult(entry.metadata, relative.as_posix(), content, byte_count)

    def package_files(self, name: str) -> Mapping[str, str]:
        """Return the bounded declarative package payload without executing it."""
        normalized_name = _bounded_text(name, "name", MAX_NAME_CHARS)
        entries, ambiguous, _ = self._discover()
        if self._granted_component_identities is None and normalized_name in ambiguous:
            raise SkillCatalogError(
                SkillCatalogReason.AMBIGUOUS_SKILL, "skill name is ambiguous across roots"
            )
        entries = self._available_entries(entries)
        if normalized_name in ambiguous and normalized_name not in entries:
            raise SkillCatalogError(
                SkillCatalogReason.AMBIGUOUS_SKILL, "skill name is ambiguous across roots"
            )
        try:
            entry = entries[normalized_name]
        except KeyError as exc:
            raise SkillCatalogError(
                SkillCatalogReason.SKILL_NOT_FOUND, "skill is not available"
            ) from exc
        if entry.files is not None:
            return entry.files
        assert entry.root is not None
        return read_skill_package(entry.root)

    def _available_entries(self, entries: dict[str, _SkillEntry]) -> dict[str, _SkillEntry]:
        if self._granted_component_identities is None:
            entries = self._pinned_entries(entries, self._installed_identities())
            disabled = (
                self._skills_state.disabled_components()
                if self._skills_state is not None
                else frozenset[tuple[str, str]]()
            )
            return {
                name: entry
                for name, entry in entries.items()
                if self._is_enabled(entry, disabled)
            }
        entries = self._pinned_entries(entries, self._granted_component_identities)
        expected = set(self._granted_component_identities)
        available = {
            entry.metadata.component_identity() for entry in entries.values()
        }
        if not expected <= available:
            raise SkillCatalogError(
                SkillCatalogReason.SKILL_NOT_FOUND,
                "granted skill component identity is unavailable",
            )
        return {
            name: entry
            for name, entry in entries.items()
            if entry.metadata.component_identity() in expected
        }

    def _is_enabled(
        self,
        entry: _SkillEntry,
        disabled: frozenset[tuple[str, str]],
    ) -> bool:
        if entry.owner is None:
            return (entry.metadata.name, entry.metadata.scope.value) not in disabled
        if self._inventory_only:
            return True
        if self._skills_state is None:
            return False
        enabled = getattr(self._skills_state, "is_component_enabled", None)
        return bool(
            enabled
            and enabled(identity=entry.metadata.component_identity(), owner=entry.owner)
        )

    def _installed_identities(self) -> tuple[SkillComponentIdentity, ...]:
        identities = getattr(self._skills_state, "installed_component_identities", None)
        if self._inventory_only or self._private_owner is None or not callable(identities):
            return ()
        return cast(
            tuple[SkillComponentIdentity, ...],
            identities(owner=self._private_owner, enabled=True),
        )

    def _pinned_entries(
        self, entries: dict[str, _SkillEntry], identities: tuple[SkillComponentIdentity, ...]
    ) -> dict[str, _SkillEntry]:
        pinned = dict(entries)
        snapshots: dict[str, _SkillEntry] = {}
        for identity in identities:
            installed = self._installed_entry(identity)
            if installed is None and identity.scope == "user" and identity.namespace != "user":
                raise SkillCatalogError(
                    SkillCatalogReason.SKILL_NOT_FOUND,
                    "granted skill component identity is unavailable",
                )
            if installed is not None:
                if identity.name in snapshots:
                    raise SkillCatalogError(
                        SkillCatalogReason.AMBIGUOUS_SKILL,
                        "multiple installed Skill identities share a name",
                    )
                snapshots[identity.name] = installed
        pinned.update(snapshots)
        return pinned

    def _installed_entry(self, identity: SkillComponentIdentity) -> _SkillEntry | None:
        if (
            self._skills_state is None
            or identity.scope != "user"
            or identity.namespace == "user"
            or identity.namespace != self._private_owner
        ):
            return None
        installed = getattr(self._skills_state, "installed_component", None)
        if not callable(installed):
            return None
        record = installed(identity=identity, owner=identity.namespace)
        if record is None:
            return None
        try:
            frontmatter_text, body_bytes = split_frontmatter(
                record.files["SKILL.md"].encode("utf-8")
            )
            parsed = parse_frontmatter(frontmatter_text)
            legacy_digest = compute_skill_digest(frontmatter_text.encode("utf-8"), body_bytes)
            package_digest = compute_private_skill_package_digest(record.files)
            if record.owner != identity.namespace or identity.digest not in {
                legacy_digest,
                package_digest,
            }:
                return None
            metadata = SkillMetadata(
                name=parsed.name,
                description=parsed.description,
                source=identity.source,
                version=parsed.version,
                license=parsed.license,
                compatibility=parsed.compatibility,
                metadata=parsed.metadata,
                digest=identity.digest,
                scope=SkillScope(identity.scope),
                namespace=identity.namespace,
                owner=record.owner,
            )
        except (KeyError, ValueError, SkillCatalogError):
            return None
        if metadata.component_identity() != identity:
            return None
        return _SkillEntry(metadata, None, record.owner, record.files)

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
                if existing.owner != entry.owner and (
                    existing.owner is not None or entry.owner is not None
                ):
                    entries.pop(name)
                    ambiguous.add(name)
                elif existing.metadata.scope == entry.metadata.scope:
                    entries.pop(name)
                    ambiguous.add(name)
                elif scope_priority(entry.metadata.scope) < scope_priority(existing.metadata.scope):
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
        private_files = read_skill_package(skill_root) if scoped.owner is not None else None
    except SkillCatalogError:
        return None
    source = skill_root.relative_to(Path(scoped.root)).as_posix() or "."
    namespace = scoped.namespace or default_namespace(scoped.scope)
    digest = (
        compute_private_skill_package_digest(private_files)
        if private_files is not None
        else compute_skill_digest(frontmatter_text.encode("utf-8"), body_bytes)
    )
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
            owner=scoped.owner,
        ),
        skill_root.resolve(), scoped.owner,
    )


def _ensure_entry_digest(entry: _SkillEntry, files: Mapping[str, str]) -> None:
    try:
        frontmatter_text, body_bytes = split_frontmatter(files["SKILL.md"].encode("utf-8"))
    except (KeyError, SkillCatalogError) as exc:
        raise SkillCatalogError(
            SkillCatalogReason.DIGEST_MISMATCH,
            "skill component digest drifted before read",
        ) from exc
    legacy_digest = compute_skill_digest(frontmatter_text.encode("utf-8"), body_bytes)
    expected = (
        compute_private_skill_package_digest(files)
        if entry.owner is not None
        else legacy_digest
    )
    if entry.metadata.digest != expected and not (
        entry.owner is not None
        and entry.files is not None
        and entry.metadata.digest == legacy_digest
    ):
        raise SkillCatalogError(
            SkillCatalogReason.DIGEST_MISMATCH,
            "skill component digest drifted before read",
        )


def _validate_live_file(root: Path, relative: Path) -> None:
    candidate = root / relative
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise SkillCatalogError(
            SkillCatalogReason.FILE_NOT_FOUND, "skill file does not exist"
        ) from exc
    if candidate.is_symlink() or not resolved.is_file() or not resolved.is_relative_to(root):
        raise SkillCatalogError(
            SkillCatalogReason.PATH_OUTSIDE_SKILL, "skill file escapes its package"
        )
