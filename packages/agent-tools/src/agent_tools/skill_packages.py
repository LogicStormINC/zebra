"""Validate an untrusted Skill ZIP in memory; never extract or execute its files."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import struct
import unicodedata
import zipfile
import zlib
from collections.abc import Iterator
from dataclasses import dataclass

from agent_tools.skills_catalog import MAX_SKILL_FILE_BYTES, SUPPORT_DIRECTORIES
from agent_tools.skills_scope import (
    SkillCatalogError,
    compute_skill_digest,
    parse_frontmatter,
    split_frontmatter,
)

MAX_ARCHIVE_BYTES = 10 * 1024 * 1024
MAX_EXPANDED_BYTES = 50 * 1024 * 1024
MAX_ENTRIES = 1000
MAX_PATH_DEPTH = 8
# ponytail: a fixed ratio ceiling bounds pathological deflate streams; revise
# this trusted constant if real packages require higher compression ratios.
MAX_COMPRESSION_RATIO = 1000
_READ_CHUNK_BYTES = 64 * 1024
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"{prefix}{number}" for prefix in ("com", "lpt") for number in range(1, 10)}
)


class SkillPackageError(ValueError):
    """A stable, sanitized rejection code suitable for an HTTP adapter."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class SkillPackageFile:
    path: str
    size: int
    sha256: str
    content: bytes


@dataclass(frozen=True)
class ValidatedSkillPackage:
    name: str
    description: str
    version: str | None
    license: str | None
    compatibility: tuple[str, ...]
    metadata: tuple[tuple[str, str], ...]
    files: tuple[SkillPackageFile, ...]
    archive_sha256: str
    content_digest: str


def validate_skill_package(archive: bytes) -> ValidatedSkillPackage:
    """Return immutable file bytes and metadata after validating every entry."""
    if not isinstance(archive, bytes):
        raise SkillPackageError("invalid_archive")
    if len(archive) > MAX_ARCHIVE_BYTES:
        raise SkillPackageError("archive_too_large")
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            files = _read_files(bundle, archive)
    except SkillPackageError:
        raise
    except (
        zipfile.BadZipFile,
        EOFError,
        OSError,
        ValueError,
        RuntimeError,
        zlib.error,
        struct.error,
    ):
        raise SkillPackageError("invalid_archive") from None
    skill = next((entry for entry in files if entry.path == "SKILL.md"), None)
    if skill is None:
        raise SkillPackageError("missing_skill_file")
    try:
        frontmatter, _ = split_frontmatter(skill.content)
        metadata = parse_frontmatter(frontmatter)
    except SkillCatalogError:
        raise SkillPackageError("invalid_skill_file") from None
    manifest = json.dumps(
        [(entry.path, entry.size, entry.sha256) for entry in files],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    return ValidatedSkillPackage(
        name=metadata.name,
        description=metadata.description,
        version=metadata.version,
        license=metadata.license,
        compatibility=metadata.compatibility,
        metadata=tuple(sorted(metadata.metadata.items())),
        files=files,
        archive_sha256=hashlib.sha256(archive).hexdigest(),
        content_digest=compute_skill_digest(manifest, b""),
    )


def _validated_path(entry: zipfile.ZipInfo) -> str:
    path = entry.orig_filename
    if path != entry.filename or "\\" in path:
        raise SkillPackageError("invalid_path")
    path = path[:-1] if entry.is_dir() else path
    parts = path.split("/")
    if len(parts) > MAX_PATH_DEPTH:
        raise SkillPackageError("path_too_deep")
    for part in parts:
        if (
            not part
            or part in {".", ".."}
            or part.endswith((".", " "))
            or any(unicodedata.category(char).startswith("C") for char in part)
            or any(char in '<>:"|?*' for char in part)
            or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED
        ):
            raise SkillPackageError("invalid_path")
    if path != "SKILL.md" and (
        parts[0] not in SUPPORT_DIRECTORIES or (len(parts) == 1 and not entry.is_dir())
    ):
        raise SkillPackageError("unsupported_path")
    if path == "SKILL.md" and entry.is_dir():
        raise SkillPackageError("invalid_path")
    return path


def _read_files(bundle: zipfile.ZipFile, archive: bytes) -> tuple[SkillPackageFile, ...]:
    entries = bundle.infolist()
    if len(entries) > MAX_ENTRIES:
        raise SkillPackageError("too_many_entries")
    explicit: set[str] = set()
    nodes: dict[str, tuple[str, bool]] = {}
    validated: list[tuple[zipfile.ZipInfo, str]] = []
    declared_total = 0
    for entry in entries:
        path = _validated_path(entry)
        mode = stat.S_IFMT(entry.external_attr >> 16)
        if mode not in {0, stat.S_IFDIR if entry.is_dir() else stat.S_IFREG}:
            raise SkillPackageError("unsupported_entry")
        if entry.flag_bits & 1:
            raise SkillPackageError("encrypted_archive")
        if entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise SkillPackageError("unsupported_compression")
        if entry.is_dir() and entry.file_size:
            raise SkillPackageError("unsupported_entry")
        if path in explicit:
            raise SkillPackageError("duplicate_path")
        explicit.add(path)
        parts = path.split("/")
        for index in range(1, len(parts) + 1):
            prefix = "/".join(parts[:index])
            key = unicodedata.normalize("NFC", prefix).casefold()
            directory = index < len(parts) or entry.is_dir()
            previous = nodes.get(key)
            if previous is not None and previous != (prefix, directory):
                raise SkillPackageError("path_conflict")
            nodes[key] = (prefix, directory)
        declared_total += entry.file_size
        if declared_total > MAX_EXPANDED_BYTES:
            raise SkillPackageError("expanded_archive_too_large")
        if path == "SKILL.md" and entry.file_size > MAX_SKILL_FILE_BYTES:
            raise SkillPackageError("skill_file_too_large")
        if entry.file_size > max(1, entry.compress_size) * MAX_COMPRESSION_RATIO:
            raise SkillPackageError("compression_ratio_exceeded")
        validated.append((entry, path))
    files: list[SkillPackageFile] = []
    total = 0
    for entry, path in validated:
        chunks: list[bytes] = []
        size = 0
        crc = 0
        # ZipFile validates the local header and overlapping entries, but its
        # reader truncates to file_size. Decode the complete compressed stream
        # ourselves so forged sizes/CRCs cannot conceal an unvalidated suffix.
        with bundle.open(entry):
            for chunk in _read_chunks(archive, entry):
                size += len(chunk)
                total += len(chunk)
                if total > MAX_EXPANDED_BYTES:
                    raise SkillPackageError("expanded_archive_too_large")
                if path == "SKILL.md" and size > MAX_SKILL_FILE_BYTES:
                    raise SkillPackageError("skill_file_too_large")
                if size > max(1, entry.compress_size) * MAX_COMPRESSION_RATIO:
                    raise SkillPackageError("compression_ratio_exceeded")
                if size > entry.file_size:
                    raise SkillPackageError("invalid_archive")
                crc = zlib.crc32(chunk, crc)
                chunks.append(chunk)
        if size != entry.file_size or crc != entry.CRC:
            raise SkillPackageError("invalid_archive")
        if not entry.is_dir():
            content = b"".join(chunks)
            files.append(SkillPackageFile(path, size, hashlib.sha256(content).hexdigest(), content))
    return tuple(sorted(files, key=lambda entry: entry.path))


def _read_chunks(archive: bytes, entry: zipfile.ZipInfo) -> Iterator[bytes]:
    name_size, extra_size = struct.unpack_from("<HH", archive, entry.header_offset + 26)
    start = entry.header_offset + 30 + name_size + extra_size
    end = start + entry.compress_size
    if start < 0 or end > len(archive):
        raise SkillPackageError("invalid_archive")
    decoder = zlib.decompressobj(-zlib.MAX_WBITS) if entry.compress_type else None
    for offset in range(start, end, _READ_CHUNK_BYTES):
        data = archive[offset : min(offset + _READ_CHUNK_BYTES, end)]
        if decoder is None:
            yield data
            continue
        while True:
            chunk = decoder.decompress(data, _READ_CHUNK_BYTES)
            data = decoder.unconsumed_tail
            if chunk:
                yield chunk
            if decoder.unused_data or (decoder.eof and offset + _READ_CHUNK_BYTES < end):
                raise SkillPackageError("invalid_archive")
            # A max_length read can leave output buffered with no input tail.
            # Keep draining bounded chunks until EOF or more input is needed.
            if decoder.eof or (not data and not chunk):
                break
    if decoder is not None and not decoder.eof:
        raise SkillPackageError("invalid_archive")
