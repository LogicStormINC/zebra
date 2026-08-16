"""Deterministic workspace materialization for the Control Plane provider.

Pure-ish system operations: git clone/checkout with a pinned revision,
archive extraction with traversal guards, and a stable content digest over
the materialized tree. No storage imports; the provider orchestrates these.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
from collections.abc import Callable
from pathlib import Path

from agent_core.domain.workspace_control import WorkspaceSource, WorkspaceSourceKind

ArchiveReader = Callable[[str], bytes]


class WorkspaceMaterializationError(ValueError):
    """Deterministic materialization failure; callers mark workspaces uncertain."""

    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code


def workspace_tree_digest(root: Path) -> str:
    """Stable sha256 over sorted relative paths and file content digests."""
    entries: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            entries.append((path.relative_to(root).as_posix(), "symlink"))
            continue
        if not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append((path.relative_to(root).as_posix(), digest))
    combined = hashlib.sha256()
    for name, digest in entries:
        combined.update(name.encode("utf-8"))
        combined.update(b"\x00")
        combined.update(digest.encode("utf-8"))
        combined.update(b"\x00")
    return combined.hexdigest()


def materialize_git(
    source: WorkspaceSource,
    target: Path,
    *,
    git_command: tuple[str, ...] = ("git",),
) -> tuple[str, str]:
    """Clone and check out the pinned revision; return (revision, digest)."""
    if source.kind is not WorkspaceSourceKind.GIT_REPOSITORY:
        raise WorkspaceMaterializationError("wrong_source_kind", "expected a git repository")
    if source.pinned_revision is None:
        raise WorkspaceMaterializationError("missing_revision", "git sources must pin a revision")
    target.parent.mkdir(parents=True, exist_ok=True)
    _run(
        git_command,
        "clone",
        "--quiet",
        "--no-checkout",
        source.locator,
        str(target),
        reason_code="clone_failed",
    )
    _run(
        (*git_command, "-C", str(target)),
        "checkout",
        "--quiet",
        "--detach",
        source.pinned_revision,
        reason_code="checkout_missing",
    )
    revision = _output(
        (*git_command, "-C", str(target)),
        "rev-parse",
        "HEAD",
        reason_code="revision_unreadable",
    ).strip()
    if not revision:
        raise WorkspaceMaterializationError("revision_unreadable", "empty HEAD revision")
    digest = workspace_tree_digest(target)
    if source.content_digest is not None and digest != source.content_digest:
        raise WorkspaceMaterializationError("digest_mismatch", "tree digest differs from source")
    return revision, digest


def materialize_archive(
    source: WorkspaceSource,
    target: Path,
    *,
    read_archive: ArchiveReader,
) -> tuple[str, str]:
    """Verify and extract the pinned archive; return (revision, digest)."""
    if source.kind is not WorkspaceSourceKind.UPLOADED_ARCHIVE:
        raise WorkspaceMaterializationError("wrong_source_kind", "expected an uploaded archive")
    if source.archive_artifact_uri is None:
        raise WorkspaceMaterializationError("archive_missing", "archive artifact uri is missing")
    payload = read_archive(source.archive_artifact_uri)
    if source.content_digest is not None:
        actual = hashlib.sha256(payload).hexdigest()
        if actual != source.content_digest:
            raise WorkspaceMaterializationError("digest_mismatch", "archive bytes differ")
    target.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
            _extract_safely(archive, target)
    except tarfile.TarError as error:
        raise WorkspaceMaterializationError(
            "archive_invalid", f"archive could not be extracted: {error}"
        ) from error
    revision = source.pinned_revision or source.archive_artifact_uri
    return revision, workspace_tree_digest(target)


def materialize_snapshot_bytes(
    payload: bytes,
    *,
    target: Path,
    expected_payload_digest: str | None = None,
) -> str:
    """Extract snapshot bytes and return the tree digest.

    ``expected_payload_digest`` (when provided) pins the byte stream; the
    caller compares the returned tree digest against the durable snapshot
    digest for semantic verification.
    """
    import hashlib

    if expected_payload_digest is not None:
        actual = hashlib.sha256(payload).hexdigest()
        if actual != expected_payload_digest:
            raise WorkspaceMaterializationError(
                "digest_mismatch", "snapshot bytes differ from the durable digest"
            )
    target.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
            _extract_safely(archive, target)
    except tarfile.TarError as error:
        raise WorkspaceMaterializationError(
            "archive_invalid", f"snapshot could not be extracted: {error}"
        ) from error
    return workspace_tree_digest(target)


def _extract_safely(archive: tarfile.TarFile, target: Path) -> None:
    root = target.resolve()
    for member in archive.getmembers():
        member_path = (target / member.name).resolve()
        if member_path != root and root not in member_path.parents:
            raise WorkspaceMaterializationError(
                "unsafe_archive_path", f"member escapes the workspace: {member.name}"
            )
        if member.issym() or member.islnk():
            raise WorkspaceMaterializationError(
                "unsafe_archive_path", f"links are not supported: {member.name}"
            )
    archive.extractall(target, filter="data")


def _run(
    command: tuple[str, ...],
    *arguments: str,
    reason_code: str,
) -> None:
    import subprocess

    completed = subprocess.run(
        (*command, *arguments),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise WorkspaceMaterializationError(
            reason_code,
            (completed.stderr or completed.stdout).strip()[:400],
        )


def _output(
    command: tuple[str, ...],
    *arguments: str,
    reason_code: str,
) -> str:
    import subprocess

    completed = subprocess.run(
        (*command, *arguments),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise WorkspaceMaterializationError(
            reason_code,
            (completed.stderr or completed.stdout).strip()[:400],
        )
    return completed.stdout
