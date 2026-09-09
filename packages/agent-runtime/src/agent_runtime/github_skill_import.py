"""Import a public GitHub Skill at an immutable commit; never extract or execute."""

from __future__ import annotations

import asyncio
import http.client
import io
import json
import re
import stat
import struct
import urllib.parse
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass

from agent_tools.skill_packages import (
    MAX_ARCHIVE_BYTES,
    MAX_COMPRESSION_RATIO,
    MAX_ENTRIES,
    MAX_EXPANDED_BYTES,
    SkillPackageError,
    _read_chunks,
    validate_skill_package,
)
from agent_tools.skills_catalog import SUPPORT_DIRECTORIES

from agent_runtime.mcp_http_egress import PublicMcpHttpsConnection


class GitHubSkillImportError(ValueError):
    def __init__(self, reason: str, *, candidates: tuple[str, ...] = ()) -> None:
        self.reason = reason
        self.candidates = candidates
        super().__init__(reason)


@dataclass(frozen=True)
class GitHubSkillImport:
    archive: bytes
    source_url: str
    commit_sha: str
    skill_path: str


async def import_github_skill(
    url: str, *, path: str | None = None, revalidate: Callable[[], None]
) -> GitHubSkillImport:
    owner, repo, ref, requested_path = _parse_url(url, path)
    prefix = f"/repos/{owner}/{repo}"
    try:
        if ref is None:
            revalidate()
            metadata = await asyncio.to_thread(_json, prefix)
            branch = metadata.get("default_branch")
            if not isinstance(branch, str) or not branch or len(branch) > 255:
                raise GitHubSkillImportError("github_invalid_response")
            ref = branch
        revalidate()
        commit = await asyncio.to_thread(
            _json, prefix + "/commits/" + urllib.parse.quote(ref, safe="")
        )
        sha = commit.get("sha")
    except GitHubSkillImportError as exc:
        if exc.reason != "github_access_or_rate_limited":
            raise
        # ponytail: codeload has a separate public quota. Its TLS-delivered git
        # archive commit comment pins a second download to an immutable SHA.
        revalidate()
        snapshot = await asyncio.to_thread(
            _download,
            "codeload.github.com",
            f"/{owner}/{repo}/zip/{urllib.parse.quote(ref or 'HEAD', safe='')}",
            MAX_ARCHIVE_BYTES,
        )
        sha = _archive_commit(snapshot)
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise GitHubSkillImportError("github_invalid_response")
    revalidate()
    archive = await asyncio.to_thread(
        _download, "codeload.github.com", f"/{owner}/{repo}/zip/{sha}", MAX_ARCHIVE_BYTES
    )
    if _archive_commit(archive) != sha:
        raise GitHubSkillImportError("github_commit_mismatch")
    selected, skill_path = await asyncio.to_thread(_select_package, archive, requested_path)
    revalidate()
    return GitHubSkillImport(selected, f"https://github.com/{owner}/{repo}", sha, skill_path)


def _archive_commit(archive: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            sha = bundle.comment.decode("ascii")
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError
        return sha
    except (ValueError, zipfile.BadZipFile):
        raise GitHubSkillImportError("github_commit_unavailable") from None


def _parse_url(url: str, path: str | None) -> tuple[str, str, str | None, str | None]:
    try:
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "github.com"
            or parsed.query
            or parsed.fragment
            or len(url) > 2048
        ):
            raise ValueError
        parts = parsed.path.strip("/").split("/")
        owner, repo = parts[:2]
        repo = repo.removesuffix(".git")
        if not all(re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", item) for item in (owner, repo)):
            raise ValueError
        if owner in {".", ".."} or repo in {".", ".."}:
            raise ValueError
        ref = None
        if len(parts) > 2:
            if len(parts) < 4 or parts[2] != "tree":
                raise ValueError
            ref = urllib.parse.unquote(parts[3])
            if not ref or any(ord(char) < 32 for char in ref):
                raise ValueError
            from_url = urllib.parse.unquote("/".join(parts[4:]))
            if path is not None and path.strip("/") != from_url:
                raise ValueError
            path = from_url
        if path is not None:
            path = path.rstrip("/")
            if path and not _safe_path(path):
                raise ValueError
    except (ValueError, TypeError):
        raise GitHubSkillImportError("invalid_github_skill_url") from None
    return owner, repo, ref, path


def _safe_path(path: str) -> bool:
    return bool(path) and all(
        item not in {"", ".", ".."}
        and "\\" not in item
        and not any(ord(char) < 32 or ord(char) == 127 for char in item)
        for item in path.split("/")
    )


def _download(host: str, target: str, limit: int) -> bytes:
    connection = PublicMcpHttpsConnection(host, timeout=20)
    try:
        connection.request(
            "GET",
            target,
            headers={
                "Accept": "application/vnd.github+json"
                if host == "api.github.com"
                else "application/zip",
                "User-Agent": "Zebra-Skill-Importer/1.0",
                "Accept-Encoding": "identity",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            reason = {
                404: "github_repository_or_ref_not_found",
                403: "github_access_or_rate_limited",
                429: "github_access_or_rate_limited",
            }.get(response.status, "github_http_error")
            raise GitHubSkillImportError(reason)
        size = response.getheader("Content-Length")
        if size is not None and int(size) > limit:
            raise GitHubSkillImportError("github_response_too_large")
        content = response.read(limit + 1)
        if len(content) > limit:
            raise GitHubSkillImportError("github_response_too_large")
        return content
    except GitHubSkillImportError:
        raise
    except (OSError, ValueError, http.client.HTTPException):
        raise GitHubSkillImportError("github_download_failed") from None
    finally:
        connection.close()


def _json(target: str) -> dict[str, object]:
    try:
        value = json.loads(_download("api.github.com", target, 1024 * 1024))
    except (UnicodeError, json.JSONDecodeError):
        raise GitHubSkillImportError("github_invalid_response") from None
    if not isinstance(value, dict):
        raise GitHubSkillImportError("github_invalid_response")
    return value


def _select_package(archive: bytes, requested: str | None) -> tuple[bytes, str]:
    try:
        return _select_zip(archive, requested)
    except GitHubSkillImportError:
        raise
    except SkillPackageError as exc:
        raise GitHubSkillImportError(exc.reason) from None
    except (
        zipfile.BadZipFile,
        EOFError,
        OSError,
        ValueError,
        RuntimeError,
        zlib.error,
        struct.error,
    ):
        raise GitHubSkillImportError("invalid_github_archive") from None


def _select_zip(archive: bytes, requested: str | None) -> tuple[bytes, str]:
    if len(archive) > MAX_ARCHIVE_BYTES:
        raise GitHubSkillImportError("archive_too_large")
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        entries = source.infolist()
        if not entries or len(entries) > MAX_ENTRIES:
            raise GitHubSkillImportError("too_many_entries")
        files: dict[str, zipfile.ZipInfo] = {}
        roots: set[str] = set()
        total = 0
        for entry in entries:
            name = entry.orig_filename.rstrip("/")
            if entry.orig_filename != entry.filename or not _safe_path(name):
                raise GitHubSkillImportError("invalid_path")
            root, _, relative = name.partition("/")
            roots.add(root)
            total += entry.file_size
            if total > MAX_EXPANDED_BYTES:
                raise GitHubSkillImportError("expanded_archive_too_large")
            if relative in files:
                raise GitHubSkillImportError("duplicate_path")
            if relative:
                files[relative] = entry
        if len(roots) != 1:
            raise GitHubSkillImportError("invalid_github_archive")
        candidates = tuple(
            sorted(
                name.removesuffix("SKILL.md").rstrip("/")
                for name, entry in files.items()
                if name.split("/")[-1] == "SKILL.md"
                and _regular(entry)
                and not any(
                    not _directory(files[parent]) for parent in _parents(name) if parent in files
                )
            )
        )
        selected = requested if requested is not None else ("" if "" in candidates else None)
        if selected is None:
            if len(candidates) > 1:
                raise GitHubSkillImportError("skill_directory_required", candidates=candidates)
            selected = candidates[0] if candidates else None
        if selected is None or selected not in candidates:
            raise GitHubSkillImportError("skill_file_not_found")
        prefix = selected + "/" if selected else ""
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as destination:
            for name, entry in sorted(files.items()):
                root_license = _license_file(name) and prefix + name not in files
                if (not name.startswith(prefix) and not root_license) or entry.is_dir():
                    continue
                relative = name if root_license else name[len(prefix) :]
                if _license_file(relative):
                    relative = "references/repository-" + relative
                    if prefix + relative in files:
                        raise GitHubSkillImportError("path_conflict")
                elif (
                    relative != "SKILL.md" and relative.split("/", 1)[0] not in SUPPORT_DIRECTORIES
                ):
                    continue
                if not _regular(entry) or entry.flag_bits & 1:
                    raise GitHubSkillImportError("unsupported_entry")
                if entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise GitHubSkillImportError("unsupported_compression")
                if entry.file_size > max(1, entry.compress_size) * MAX_COMPRESSION_RATIO:
                    raise GitHubSkillImportError("compression_ratio_exceeded")
                content = bytearray()
                with source.open(entry):
                    for chunk in _read_chunks(archive, entry):
                        content.extend(chunk)
                        if len(content) > entry.file_size:
                            raise GitHubSkillImportError("invalid_github_archive")
                if len(content) != entry.file_size or zlib.crc32(content) != entry.CRC:
                    raise GitHubSkillImportError("invalid_github_archive")
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                destination.writestr(info, content)
        result = output.getvalue()
        validate_skill_package(result)
        return result, selected


def _regular(entry: zipfile.ZipInfo) -> bool:
    return not entry.is_dir() and stat.S_IFMT(entry.external_attr >> 16) in {0, stat.S_IFREG}


def _license_file(path: str) -> bool:
    return path.upper() in {"LICENSE", "LICENSE.MD", "LICENSE.TXT", "COPYING", "NOTICE"}


def _directory(entry: zipfile.ZipInfo) -> bool:
    return entry.is_dir() and stat.S_IFMT(entry.external_attr >> 16) in {0, stat.S_IFDIR}


def _parents(path: str) -> tuple[str, ...]:
    parts = path.split("/")
    return tuple("/".join(parts[:index]) for index in range(1, len(parts)))
