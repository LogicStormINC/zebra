from __future__ import annotations

import io
import random
import stat
import struct
import warnings
import zipfile
import zlib
from dataclasses import FrozenInstanceError

import pytest
from agent_tools import skill_packages as packages

SKILL = b"---\nname: example\ndescription: Example skill\nversion: 1\nlicense: MIT\n---\nHello"


def archive(
    entries: list[tuple[str | zipfile.ZipInfo, bytes]],
    compression: int = zipfile.ZIP_STORED,
) -> bytes:
    output = io.BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(output, "w", compression=compression) as bundle:
        warnings.simplefilter("ignore", UserWarning)
        for path, content in entries:
            bundle.writestr(path, content)
    return output.getvalue()


def reject(payload: bytes, reason: str) -> None:
    with pytest.raises(packages.SkillPackageError) as caught:
        packages.validate_skill_package(payload)
    assert caught.value.reason == reason
    assert str(caught.value) == reason
    assert caught.value.__suppress_context__ or caught.value.__context__ is None


def test_metadata_and_binary_assets_are_immutable() -> None:
    skill = SKILL.replace(
        b"license: MIT", b"license: MIT\ncompatibility: python linux\nauthor: Luke"
    )
    result = packages.validate_skill_package(
        archive([("assets/", b""), ("SKILL.md", skill), ("assets/image.bin", b"\x00\xff")])
    )
    assert (result.name, result.description, result.version, result.license) == (
        "example",
        "Example skill",
        "1",
        "MIT",
    )
    assert result.metadata == (("author", "Luke"),)
    assert result.compatibility == ("python", "linux")
    assert [file.path for file in result.files] == ["SKILL.md", "assets/image.bin"]
    assert result.files[1].content == b"\x00\xff"
    with pytest.raises(FrozenInstanceError):
        result.name = "changed"  # type: ignore[misc]


def test_content_digest_ignores_zip_order_timestamp_and_directory_entries() -> None:
    old = zipfile.ZipInfo("SKILL.md", date_time=(2020, 1, 1, 0, 0, 0))
    new = zipfile.ZipInfo("SKILL.md", date_time=(2025, 1, 1, 0, 0, 0))
    first = packages.validate_skill_package(archive([(old, SKILL), ("assets/a", b"a")]))
    second = packages.validate_skill_package(
        archive([("assets/", b""), ("assets/a", b"a"), (new, SKILL)])
    )
    changed = packages.validate_skill_package(archive([(old, SKILL), ("assets/a", b"b")]))
    assert first.content_digest == second.content_digest
    assert first.archive_sha256 != second.archive_sha256
    assert first.content_digest != changed.content_digest


@pytest.mark.parametrize(
    "path",
    [
        "/assets/a",
        "C:/assets/a",
        "assets\\a",
        "assets/../a",
        "assets/./a",
        "assets//a",
        "assets/a\x01",
        "assets/a.",
        "assets/NUL",
        "assets/a:b",
    ],
)
def test_unsafe_paths(path: str) -> None:
    reject(archive([("SKILL.md", SKILL), (path, b"a")]), "invalid_path")


def test_original_nul_filename_is_rejected() -> None:
    payload = archive([("SKILL.md", SKILL), ("assets/xYz", b"a")])
    reject(payload.replace(b"assets/xYz", b"assets/x\x00z"), "invalid_path")


@pytest.mark.parametrize(
    "paths,reason",
    [
        (["assets/a", "assets/a"], "duplicate_path"),
        (["assets/A", "assets/a"], "path_conflict"),
        (["assets/\u00e9", "assets/e\u0301"], "path_conflict"),
        (["assets/A/x", "assets/a/y"], "path_conflict"),
        (["assets/a", "assets/a/b"], "path_conflict"),
        (["assets/a/b", "assets/a"], "path_conflict"),
    ],
)
def test_collisions(paths: list[str], reason: str) -> None:
    reject(archive([("SKILL.md", SKILL), *((path, b"a") for path in paths)]), reason)


@pytest.mark.parametrize("mode", [stat.S_IFLNK, stat.S_IFCHR, stat.S_IFIFO, stat.S_IFDIR])
def test_non_regular_entries(mode: int) -> None:
    entry = zipfile.ZipInfo("assets/a")
    entry.create_system = 3
    entry.external_attr = (mode | 0o644) << 16
    reject(archive([("SKILL.md", SKILL), (entry, b"a")]), "unsupported_entry")


@pytest.mark.parametrize("skill", [b"no metadata", b"\xff", SKILL + b"\x00", b"---\nname: x\n---"])
def test_invalid_skill(skill: bytes) -> None:
    reject(archive([("SKILL.md", skill)]), "invalid_skill_file")


def test_missing_and_unsupported_paths() -> None:
    reject(archive([("assets/a", b"a")]), "missing_skill_file")
    reject(archive([("other/a", b"a")]), "unsupported_path")
    reject(archive([("assets", b"a")]), "unsupported_path")
    reject(archive([("SKILL.md/", b"")]), "invalid_path")
    reject(archive([("SKILL.md", SKILL), ("assets/", b"unexpected")]), "unsupported_entry")


@pytest.mark.parametrize(
    "constant,value,reason",
    [
        ("MAX_ARCHIVE_BYTES", 5, "archive_too_large"),
        ("MAX_EXPANDED_BYTES", 5, "expanded_archive_too_large"),
        ("MAX_ENTRIES", 1, "too_many_entries"),
        ("MAX_PATH_DEPTH", 1, "path_too_deep"),
        ("MAX_SKILL_FILE_BYTES", 5, "skill_file_too_large"),
    ],
)
def test_limits(monkeypatch: pytest.MonkeyPatch, constant: str, value: int, reason: str) -> None:
    monkeypatch.setattr(packages, constant, value)
    reject(archive([("SKILL.md", SKILL), ("assets/a", b"a")]), reason)


def test_deflate_and_ratio(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = archive([("SKILL.md", SKILL), ("assets/a", b"a" * 10000)], zipfile.ZIP_DEFLATED)
    assert len(packages.validate_skill_package(payload).files) == 2
    monkeypatch.setattr(packages, "MAX_COMPRESSION_RATIO", 10)
    reject(payload, "compression_ratio_exceeded")


def test_bad_crc_truncation_and_non_zip_are_sanitized() -> None:
    payload = archive([("SKILL.md", SKILL)])
    reject(payload.replace(b"Hello", b"Other"), "invalid_archive")
    reject(payload[:-15], "invalid_archive")
    reject(b"untrusted secret text", "invalid_archive")


@pytest.mark.parametrize(
    "field,value,reason",
    [
        (8, 1, "encrypted_archive"),
        (10, zipfile.ZIP_BZIP2, "unsupported_compression"),
    ],
)
def test_central_directory_flags(field: int, value: int, reason: str) -> None:
    payload = bytearray(archive([("SKILL.md", SKILL)]))
    central = payload.index(b"PK\x01\x02")
    struct.pack_into("<H", payload, central + field, value)
    reject(bytes(payload), reason)


def forged_asset(content: bytes, declared: bytes, compression: int, suffix: bytes = b"") -> bytes:
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    raw = compressor.compress(content) + compressor.flush() if compression else content
    payload = bytearray(archive([("SKILL.md", SKILL), ("assets/a", raw + suffix)]))
    with zipfile.ZipFile(io.BytesIO(payload)) as bundle:
        local = bundle.getinfo("assets/a").header_offset
    central = payload.rindex(b"PK\x01\x02")
    for base, method_offset, crc_offset, size_offset in ((local, 8, 14, 22), (central, 10, 16, 24)):
        struct.pack_into("<H", payload, base + method_offset, compression)
        struct.pack_into("<I", payload, base + crc_offset, zlib.crc32(declared))
        struct.pack_into("<I", payload, base + size_offset, len(declared))
    return bytes(payload)


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_underdeclared_stream_with_matching_prefix_crc_is_rejected(compression: int) -> None:
    payload = forged_asset(b"ABCDEF", b"ABC", compression)
    with zipfile.ZipFile(io.BytesIO(payload)) as bundle:
        assert bundle.read("assets/a") == b"ABC"  # Demonstrates the stdlib truncation.
    reject(payload, "invalid_archive")


def test_deflate_trailing_bytes_are_rejected() -> None:
    reject(forged_asset(b"ABC", b"ABC", zipfile.ZIP_DEFLATED, b"suffix"), "invalid_archive")


def test_incomplete_deflate_stream_is_rejected() -> None:
    payload = bytearray(forged_asset(b"ABC", b"ABC", zipfile.ZIP_DEFLATED))
    with zipfile.ZipFile(io.BytesIO(payload)) as bundle:
        entry = bundle.getinfo("assets/a")
    central = payload.rindex(b"PK\x01\x02")
    struct.pack_into("<I", payload, entry.header_offset + 18, entry.compress_size - 1)
    struct.pack_into("<I", payload, central + 20, entry.compress_size - 1)
    reject(bytes(payload), "invalid_archive")


def test_deflate_multiple_output_chunks() -> None:
    content = bytes(range(256)) * 1000
    result = packages.validate_skill_package(
        archive([("SKILL.md", SKILL), ("assets/a", content)], zipfile.ZIP_DEFLATED)
    )
    assert result.files[1].content == content


@pytest.mark.parametrize("size", [65535, 65536, 65537, 65538, 131071, 131072, 131073])
@pytest.mark.parametrize("compressible", [True, False])
def test_deflate_chunk_boundaries(size: int, compressible: bool) -> None:
    content = b"A" * size if compressible else random.Random(42).randbytes(size)
    result = packages.validate_skill_package(
        archive([("SKILL.md", SKILL), ("assets/a", content)], zipfile.ZIP_DEFLATED)
    )
    assert result.files[1].content == content


def test_read_bound_is_enforced_beyond_declared_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = forged_asset(b"A" * 1000, b"A", zipfile.ZIP_DEFLATED)
    monkeypatch.setattr(packages, "MAX_EXPANDED_BYTES", len(SKILL) + 2)
    reject(payload, "expanded_archive_too_large")
