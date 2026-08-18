"""Local materialization coverage for the Workspace Control Plane provider."""

from __future__ import annotations

import io
import subprocess
import tarfile
from hashlib import sha256
from pathlib import Path

import pytest
from agent_core.domain.workspace_control import WorkspaceSource, WorkspaceSourceKind
from agent_runtime.workspace_materialization import (
    WorkspaceMaterializationError,
    materialize_archive,
    materialize_git,
    materialize_snapshot_bytes,
    workspace_tree_digest,
)


def _git_repo(tmp_path: Path) -> tuple[str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--quiet", "--initial-branch=main")
    (repo / "README.md").write_text("# workspace\nhello\n")
    _git(repo, "config", "user.email", "e2e@example")
    _git(repo, "config", "user.name", "E2E")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "initial")
    revision = _git_out(repo, "rev-parse", "HEAD").strip()
    return str(repo), revision


def _git(repo: Path, *arguments: str) -> None:
    subprocess.run(("git", "-C", str(repo), *arguments), check=True, capture_output=True)


def _git_out(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", "-C", str(repo), *arguments), check=True, capture_output=True, text=True
    ).stdout


def _archive_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, content in sorted(files.items()):
            payload = content.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def test_tree_digest_is_content_ordered(tmp_path: Path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    for root in (first, second):
        root.mkdir()
        (root / "x.txt").write_text("one")
        (root / "dir").mkdir()
        (root / "dir" / "y.txt").write_text("two")
    assert workspace_tree_digest(first) == workspace_tree_digest(second)
    (second / "x.txt").write_text("changed")
    assert workspace_tree_digest(first) != workspace_tree_digest(second)


def test_git_materialization_pins_and_digests(tmp_path: Path) -> None:
    locator, revision = _git_repo(tmp_path)
    source = WorkspaceSource(
        kind=WorkspaceSourceKind.GIT_REPOSITORY,
        locator=locator,
        pinned_revision=revision,
    )
    target = tmp_path / "materialized"
    got_revision, digest = materialize_git(source, target)
    assert got_revision == revision
    assert digest == workspace_tree_digest(target)
    assert (target / "README.md").read_text().startswith("# workspace")


def test_git_materialization_rejects_unknown_revision(tmp_path: Path) -> None:
    locator, _ = _git_repo(tmp_path)
    source = WorkspaceSource(
        kind=WorkspaceSourceKind.GIT_REPOSITORY,
        locator=locator,
        pinned_revision="0" * 40,
    )
    with pytest.raises(WorkspaceMaterializationError, match="checkout_missing"):
        materialize_git(source, tmp_path / "missing")


def test_git_materialization_rejects_forged_digest(tmp_path: Path) -> None:
    locator, revision = _git_repo(tmp_path)
    source = WorkspaceSource(
        kind=WorkspaceSourceKind.GIT_REPOSITORY,
        locator=locator,
        pinned_revision=revision,
        content_digest="c" * 64,
    )
    with pytest.raises(WorkspaceMaterializationError, match="digest_mismatch"):
        materialize_git(source, tmp_path / "forged")


def test_archive_materialization_verifies_and_extracts(tmp_path: Path) -> None:
    payload = _archive_bytes({"README.md": "archived", "src/main.py": "print('hi')\n"})
    source = WorkspaceSource(
        kind=WorkspaceSourceKind.UPLOADED_ARCHIVE,
        locator="artifact://zebra/uploads/repo.tar.gz",
        archive_artifact_uri="artifact://zebra/uploads/repo.tar.gz",
        content_digest=sha256(payload).hexdigest(),
    )
    target = tmp_path / "extracted"
    revision, digest = materialize_archive(source, target, read_archive=lambda uri: payload)
    assert revision == source.archive_artifact_uri
    assert (target / "README.md").read_text() == "archived"
    assert digest == workspace_tree_digest(target)


def test_archive_materialization_rejects_digest_mismatch(tmp_path: Path) -> None:
    payload = _archive_bytes({"README.md": "archived"})
    source = WorkspaceSource(
        kind=WorkspaceSourceKind.UPLOADED_ARCHIVE,
        locator="artifact://zebra/uploads/repo.tar.gz",
        archive_artifact_uri="artifact://zebra/uploads/repo.tar.gz",
        content_digest="d" * 64,
    )
    with pytest.raises(WorkspaceMaterializationError, match="digest_mismatch"):
        materialize_archive(source, tmp_path / "x", read_archive=lambda uri: payload)


def test_archive_materialization_blocks_traversal(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        payload = b"evil"
        info = tarfile.TarInfo("../escape.txt")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    source = WorkspaceSource(
        kind=WorkspaceSourceKind.UPLOADED_ARCHIVE,
        locator="artifact://zebra/uploads/evil.tar.gz",
        archive_artifact_uri="artifact://zebra/uploads/evil.tar.gz",
    )
    with pytest.raises(WorkspaceMaterializationError, match="unsafe_archive_path"):
        materialize_archive(source, tmp_path / "safe", read_archive=lambda uri: buffer.getvalue())
    assert not (tmp_path / "escape.txt").exists()


def test_snapshot_bytes_roundtrip_and_mismatch(tmp_path: Path) -> None:
    payload = _archive_bytes({"README.md": "snapshotted"})
    digest = materialize_snapshot_bytes(
        payload,
        expected_payload_digest=sha256(payload).hexdigest(),
        target=tmp_path / "restored",
    )
    assert (tmp_path / "restored" / "README.md").read_text() == "snapshotted"
    assert digest == workspace_tree_digest(tmp_path / "restored")
    with pytest.raises(WorkspaceMaterializationError, match="digest_mismatch"):
        materialize_snapshot_bytes(
            payload,
            expected_payload_digest="e" * 64,
            target=tmp_path / "wrong",
        )
