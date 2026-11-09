"""Verify both immutable deployed-source evidence and this refactored candidate."""

import hashlib
import json
import tarfile
from pathlib import Path

FROZEN_MANIFEST_SHA256 = "a63a7fc1b5e988149c1b50ef9b27423571cf1f90a52c97a7539a2f716e559203"
ORIGINAL_ARCHIVE_SHA256 = "34ba05a183cec6d93f88f68033ea624ed1fdc2557e5e759508bc7ae6e3385ad5"


def verify_source_projection(root: Path) -> None:
    manifest_path = root / "frozen-manifest.json"
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == FROZEN_MANIFEST_SHA256
    original = json.loads(manifest_path.read_bytes())["files"]
    archive_path = (
        root.parents[1] / "docs/evidence/ca-baseline-gate-02/original-chat-recovery.tar.gz"
    )
    assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == ORIGINAL_ARCHIVE_SHA256
    with tarfile.open(archive_path, "r:gz") as archive:
        for name, digest in original.items():
            member = archive.extractfile("cloud-patches/chat-recovery/" + name)
            assert member is not None, name
            assert hashlib.sha256(member.read()).hexdigest() == digest, name
    candidate = json.loads((root / "source-projection.json").read_bytes())
    expected = set(original) | {str(p.relative_to(root)) for p in root.rglob("*.py")}
    assert candidate["schema_version"] == 1
    assert set(candidate["files"]) == expected, "candidate source inventory changed"
    for name, digest in candidate["files"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, name
