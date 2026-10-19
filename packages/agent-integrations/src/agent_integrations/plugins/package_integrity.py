"""Snapshot and validate bounded directory packages; never extract or execute."""

from __future__ import annotations

import io
import json
import os
import stat
import unicodedata
import zipfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from agent_core.domain.plugin_packages import (
    PluginPackageManifest,
    PluginSkillComponent,
    normalize_plugin_manifest,
    normalize_plugin_path,
    plugin_package_digest,
)
from agent_core.domain.plugins import PluginManifest
from agent_tools.skill_packages import (
    MAX_ENTRIES,
    MAX_EXPANDED_BYTES,
    MAX_PATH_DEPTH,
    SkillPackageError,
    validate_skill_package,
)
from agent_tools.skills_catalog import MAX_SKILL_FILE_BYTES


class PluginPackageError(ValueError):
    """Sanitized Cloud package validation failure."""


@dataclass(frozen=True)
class PluginPackageFile:
    path: str
    size: int
    sha256: str
    content: bytes


@dataclass(frozen=True)
class ValidatedPluginPackage:
    """Immutable validated bytes; later publication must use these bytes."""

    manifest: PluginPackageManifest
    canonical_manifest: str
    manifest_digest: str
    package_digest: str
    files: tuple[PluginPackageFile, ...]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise PluginPackageError("duplicate_json_key")
        document[key] = value
    return document


def load_plugin_package(bundle_root: Path) -> ValidatedPluginPackage:
    """Validate actual files, preserve legacy manifest hash, hash all content."""
    try:
        files = _snapshot_files(bundle_root)
        manifest_file = next((file for file in files if file.path == "plugin.json"), None)
        if manifest_file is None:
            raise PluginPackageError("missing_manifest")
        document = json.loads(manifest_file.content, object_pairs_hook=_unique_object)
        manifest = normalize_plugin_manifest(document)
        original = (
            PluginManifest.validate_document(document)
            if document.get("manifest_version", "0.1") == "0.1"
            else manifest
        )
        canonical = original.canonical_json()
        contents = tuple(file for file in files if file.path != "plugin.json")
        _validate_skills(manifest, contents)
    except PluginPackageError:
        raise
    except SkillPackageError as error:
        raise PluginPackageError(error.reason) from None
    except (OSError, ValueError, RuntimeError, RecursionError):
        raise PluginPackageError("invalid_package") from None
    return ValidatedPluginPackage(
        manifest,
        canonical,
        "sha256:" + sha256(canonical.encode()).hexdigest(),
        plugin_package_digest(
            canonical, ((file.path, file.size, file.sha256) for file in contents),
        ),
        contents,
    )


def _snapshot_files(bundle_root: Path) -> tuple[PluginPackageFile, ...]:
    files: list[PluginPackageFile] = []
    seen: set[str] = set()
    total = 0
    entries = 0

    def visit(directory_fd: int, parts: tuple[str, ...]) -> None:
        nonlocal total, entries
        with os.scandir(directory_fd) as children:
            for child in children:
                name = child.name
                entries += 1
                if entries > MAX_ENTRIES:
                    raise PluginPackageError("too_many_entries")
                relative = (*parts, unicodedata.normalize("NFC", name))
                if len(relative) > MAX_PATH_DEPTH:
                    raise PluginPackageError("path_too_deep")
                path = normalize_plugin_path("/".join(relative))
                key = path.casefold()
                if key in seen:
                    raise PluginPackageError("path_conflict")
                seen.add(key)
                mode = os.stat(name, dir_fd=directory_fd, follow_symlinks=False).st_mode
                if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                    raise PluginPackageError("unsupported_entry")
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                if stat.S_ISDIR(mode):
                    flags |= os.O_DIRECTORY
                child_fd = os.open(name, flags, dir_fd=directory_fd)
                try:
                    if stat.S_ISDIR(mode):
                        visit(child_fd, relative)
                        continue
                    if not stat.S_ISREG(os.fstat(child_fd).st_mode):
                        raise PluginPackageError("unsupported_entry")
                    chunks: list[bytes] = []
                    size = 0
                    while chunk := os.read(child_fd, 64 * 1024):
                        size += len(chunk)
                        total += len(chunk)
                        if total > MAX_EXPANDED_BYTES:
                            raise PluginPackageError("package_too_large")
                        if (
                            relative[-1] in {"plugin.json", "SKILL.md"}
                            and size > MAX_SKILL_FILE_BYTES
                        ):
                            raise PluginPackageError("metadata_too_large")
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    files.append(
                        PluginPackageFile(path, size, sha256(content).hexdigest(), content)
                    )
                finally:
                    os.close(child_fd)

    root_fd = os.open(bundle_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        visit(root_fd, ())
    finally:
        os.close(root_fd)
    return tuple(sorted(files, key=lambda file: file.path))


def _validate_skills(manifest: PluginPackageManifest, files: tuple[PluginPackageFile, ...]) -> None:
    remaining = {file.path for file in files}
    for component in manifest.components:
        if not isinstance(component, PluginSkillComponent):
            continue
        root = unicodedata.normalize("NFC", component.skill_root) + "/"
        contents = [file for file in files if file.path.startswith(root)]
        output = io.BytesIO()
        # ponytail: bounded in-memory ZIP reuses the existing public Skill
        # validator; replace with a shared file validator if package scale grows.
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for file in contents:
                bundle.writestr(file.path.removeprefix(root), file.content)
                remaining.discard(file.path)
        validate_skill_package(output.getvalue())
    if remaining:
        raise PluginPackageError("unclaimed_file")
