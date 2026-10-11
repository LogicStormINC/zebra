from __future__ import annotations

import io
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.identifiers import new_artifact_id, new_session_id
from agent_core.ports.artifact_payload_store import (
    BoundedArtifactPayloadReaderPort,
    ImmutableArtifactPayloadStorePort,
)
from agent_storage.artifact_payloads import SQLiteArtifactPayloadStore

NOW = datetime(2026, 10, 8, tzinfo=UTC)


def test_legacy_filename_is_bound_after_verified_retry(tmp_path):
    store = SQLiteArtifactPayloadStore(tmp_path / "artifacts.db")
    payload, identifier = _payload(), new_artifact_id()
    stored = store.store_payload(payload, artifact_id=identifier)
    with sqlite3.connect(tmp_path / "artifacts.db") as connection:
        connection.execute("UPDATE artifact_payloads SET file_name=NULL,file_name_recorded=0")
    fresh = SQLiteArtifactPayloadStore(tmp_path / "artifacts.db")
    assert fresh.store_payload(payload, artifact_id=identifier) == stored
    with pytest.raises(ValueError, match="metadata conflicts"):
        fresh.store_payload(
            payload.model_copy(update={"file_name": "changed.bin"}), artifact_id=identifier
        )


def test_actual_legacy_schema_and_file_uri_migrate_without_rewriting_evidence(tmp_path):
    database = tmp_path / "legacy.db"
    store = SQLiteArtifactPayloadStore(database)
    payload, identifier = _payload(), new_artifact_id()
    original = store.store_payload(payload, artifact_id=identifier)
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE artifact_payloads DROP COLUMN file_name")
        connection.execute("ALTER TABLE artifact_payloads DROP COLUMN file_name_recorded")
        connection.execute("UPDATE artifact_payloads SET uri=access_uri,access_uri=NULL")
    fresh = SQLiteArtifactPayloadStore(database)
    legacy = fresh.get_payload(identifier)
    assert legacy.uri == original.access_uri
    assert fresh.store_payload_immutable(payload, artifact_id=identifier) == legacy
    assert (
        fresh.read_payload_bytes_bounded(identifier, max_bytes=len(payload.payload))
        == payload.payload
    )
    with pytest.raises(ValueError, match="metadata conflicts"):
        fresh.store_payload_immutable(
            payload.model_copy(update={"file_name": "changed.bin"}), artifact_id=identifier
        )


def test_interrupted_prune_is_reclaimed_by_sweep(tmp_path, monkeypatch):
    store = SQLiteArtifactPayloadStore(tmp_path / "artifacts.db")
    payload, identifier = _payload(), new_artifact_id()
    store.store_payload(payload, artifact_id=identifier)
    original = Path.unlink
    with monkeypatch.context() as patch:
        patch.setattr(
            Path, "unlink", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("crash"))
        )
        with pytest.raises(OSError, match="crash"):
            store.prune_payload(identifier)
    assert store.inspect_payload(identifier).status.value == "pruned"
    assert len(store.sweep_expired_payloads(as_of=NOW)) == 1
    assert store.sweep_expired_payloads(as_of=NOW) == []
    assert Path.unlink is original


def _payload() -> ArtifactPayloadWrite:
    return ArtifactPayloadWrite(
        session_id=new_session_id(),
        kind="coverage",
        mime_type="application/octet-stream",
        payload=b"complete",
        file_name="body.bin",
        created_at=NOW,
        retained_until=NOW + timedelta(days=1),
    )


@pytest.mark.parametrize(
    "methods",
    [
        ("store_payload_immutable", "store_payload_immutable"),
        ("store_payload_immutable", "store_payload"),
        ("store_payload", "store_payload"),
    ],
)
@pytest.mark.parametrize("different", [False, True])
def test_publication_serializes_separate_processes(
    tmp_path: Path,
    methods: tuple[str, str],
    different: bool,
) -> None:
    store = SQLiteArtifactPayloadStore(tmp_path / "artifacts.db")
    payload, identifier = _payload(), new_artifact_id()
    script = """
import sys
from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.identifiers import ArtifactId
from agent_storage.artifact_payloads import SQLiteArtifactPayloadStore
from uuid import UUID
store = SQLiteArtifactPayloadStore(sys.argv[1])
payload = ArtifactPayloadWrite.model_validate_json(sys.argv[3])
print('ready', flush=True)
sys.stdin.readline()
try:
    getattr(store, sys.argv[4])(payload, artifact_id=ArtifactId(UUID(sys.argv[2])))
    print('stored', flush=True)
except ValueError:
    print('conflict', flush=True)
"""
    children = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                str(tmp_path / "artifacts.db"),
                str(identifier),
                payload.model_copy(update={"payload": body}).model_dump_json(),
                method,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=os.environ.copy(),
        )
        for method, body in zip(
            methods, [payload.payload, b"different" if different else payload.payload], strict=True
        )
    ]
    try:
        for child in children:
            assert child.stdout is not None
            assert child.stdout.readline().strip() == "ready"
        for child in children:
            assert child.stdin is not None
            child.stdin.write("go\n")
            child.stdin.flush()
        results = [child.communicate(timeout=20) for child in children]
        assert all(child.returncode == 0 for child in children), results
        assert sorted(out.strip() for out, _ in results) == (
            ["conflict", "stored"] if different else ["stored", "stored"]
        )
        assert store.read_payload_bytes(identifier) in {payload.payload, b"different"}
        stored = store.get_payload(identifier)
        assert stored is not None
        assert len(store.read_payload_bytes(identifier)) == stored.size_bytes
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.communicate()


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "other"),
        ("mime_type", "text/plain"),
        ("file_name", "other.json"),
        ("created_at", NOW + timedelta(seconds=1)),
        ("retained_until", None),
        ("session_id", new_session_id()),
        ("payload", b"different"),
    ],
)
def test_retry_compares_immutable_metadata(
    tmp_path: Path,
    field: str,
    value: Any,
) -> None:
    store, payload, identifier = (
        SQLiteArtifactPayloadStore(tmp_path / "db"),
        _payload(),
        new_artifact_id(),
    )
    first = store.store_payload_immutable(payload, artifact_id=identifier)
    assert isinstance(store, ImmutableArtifactPayloadStorePort)
    assert isinstance(store, BoundedArtifactPayloadReaderPort)
    assert store.store_payload(payload, artifact_id=identifier) == first
    with pytest.raises(ValueError, match="metadata conflicts"):
        store.store_payload(payload.model_copy(update={field: value}), artifact_id=identifier)
    assert store.get_payload(identifier) == first
    assert store.read_payload_bytes(identifier) == payload.payload


@pytest.mark.parametrize("body", [b"complete", b"comp", b"", b"conflict", b"complete-extra"])
@pytest.mark.parametrize("method", ["store_payload_immutable", "store_payload"])
def test_orphan_adopted_only_when_exact(
    tmp_path: Path,
    body: bytes,
    method: str,
) -> None:
    root = tmp_path / "objects"
    payload, identifier = _payload(), new_artifact_id()
    path = root / str(payload.session_id) / str(identifier) / "payload.bin"
    path.parent.mkdir(parents=True)
    path.write_bytes(body)
    store = SQLiteArtifactPayloadStore(tmp_path / "db", root_path=root)
    if body == payload.payload:
        stored = getattr(store, method)(payload, artifact_id=identifier)
        fresh = SQLiteArtifactPayloadStore(tmp_path / "db", root_path=root)
        assert fresh.get_payload(identifier) == stored
        assert fresh.read_payload_bytes(identifier) == body
    else:
        with pytest.raises(ValueError, match="bytes do not match"):
            getattr(store, method)(payload, artifact_id=identifier)
        assert store.get_payload(identifier) is None
    assert path.read_bytes() == body


@pytest.mark.parametrize("other_session", [False, True])
def test_orphan_under_other_locator_is_not_overwritten(tmp_path: Path, other_session: bool) -> None:
    root, payload, identifier = tmp_path / "objects", _payload(), new_artifact_id()
    session = new_session_id() if other_session else payload.session_id
    path = root / str(session) / str(identifier) / "payload.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(payload.payload)
    store = SQLiteArtifactPayloadStore(tmp_path / "db", root_path=root)
    with pytest.raises(ValueError, match="orphan identity conflicts"):
        store.store_payload_immutable(payload, artifact_id=identifier)
    assert path.read_bytes() == payload.payload
    assert store.get_payload(identifier) is None


@pytest.mark.parametrize("body", [b"changed!", b"comp", b"complete" * 10])
def test_corruption_never_repaired_by_retry(tmp_path: Path, body: bytes) -> None:
    store, payload = SQLiteArtifactPayloadStore(tmp_path / "db"), _payload()
    stored = store.store_payload(payload)
    path = store._stored_payload_path(stored)
    path.write_bytes(body)
    for publish in (store.store_payload, store.store_payload_immutable):
        with pytest.raises(ValueError, match="bytes do not match"):
            publish(payload, artifact_id=stored.artifact_id)
    assert path.read_bytes() == body
    assert store.get_payload(stored.artifact_id) == stored


@pytest.mark.parametrize("limit", [-1, True, 1.5, "8", None])
def test_invalid_limits_rejected_before_read(tmp_path: Path, limit: Any) -> None:
    store = SQLiteArtifactPayloadStore(tmp_path / "db")
    with pytest.raises(ValueError, match="non-negative integer"):
        store.read_payload_bytes_bounded(new_artifact_id(), max_bytes=limit)


def test_reads_are_physically_bounded_including_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, payload, identifier = (
        SQLiteArtifactPayloadStore(tmp_path / "db"),
        _payload(),
        new_artifact_id(),
    )
    store.store_payload(payload, artifact_id=identifier)
    reads: list[int] = []

    class Body(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            assert size is not None
            reads.append(size)
            assert 0 <= size <= len(payload.payload) + 1
            return super().read(size)

    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: Body(payload.payload * 100))
    with pytest.raises(ValueError, match="bytes do not match"):
        store.read_payload_bytes_bounded(identifier, max_bytes=len(payload.payload))
    with pytest.raises(ValueError, match="bytes do not match"):
        store.store_payload_immutable(payload, artifact_id=identifier)
    assert reads == [len(payload.payload) + 1] * 2


@pytest.mark.parametrize(
    "column,value", [("size_bytes", 2), ("size_bytes", -1), ("sha256", "0" * 64)]
)
def test_dishonest_metadata_fails(tmp_path: Path, column: str, value: object) -> None:
    store, payload = SQLiteArtifactPayloadStore(tmp_path / "db"), _payload()
    stored = store.store_payload(payload)
    with store._database.connect() as connection:
        connection.execute(
            f"UPDATE artifact_payloads SET {column} = ? WHERE artifact_id = ?",
            (value, str(stored.artifact_id)),
        )
    with pytest.raises(ValueError):
        store.read_payload_bytes_bounded(stored.artifact_id, max_bytes=len(payload.payload))


def test_empty_and_limit_boundary(tmp_path: Path) -> None:
    store, payload = SQLiteArtifactPayloadStore(tmp_path / "db"), _payload()
    stored = store.store_payload(payload)
    with pytest.raises(ValueError, match="exceeds byte limit"):
        store.read_payload_bytes_bounded(stored.artifact_id, max_bytes=len(payload.payload) - 1)
    assert (
        store.read_payload_bytes_bounded(stored.artifact_id, max_bytes=len(payload.payload))
        == payload.payload
    )
    empty = store.store_payload(payload.model_copy(update={"payload": b""}))
    assert store.read_payload_bytes_bounded(empty.artifact_id, max_bytes=0) == b""


def test_orphan_preflight_is_physically_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, payload, identifier = (
        SQLiteArtifactPayloadStore(tmp_path / "db"),
        _payload(),
        new_artifact_id(),
    )
    path = store._payload_path(payload.session_id, identifier, payload.file_name)
    path.parent.mkdir(parents=True)
    path.write_bytes(payload.payload * 100)
    original_open = Path.open
    reads: list[int] = []
    streams: list[io.BytesIO] = []

    class Body(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            assert size is not None and size == len(payload.payload) + 1
            reads.append(size)
            return super().read(size)

    def open_bounded(path: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if mode == "rb":
            body = Body(payload.payload * 100)
            streams.append(body)
            return body
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_bounded)
    with pytest.raises(ValueError, match="bytes do not match"):
        store.store_payload_immutable(payload, artifact_id=identifier)
    assert reads == [len(payload.payload) + 1]
    assert streams[0].closed
    assert store.get_payload(identifier) is None


@pytest.mark.parametrize("pruned", [False, True])
def test_retry_never_recreates_missing_or_pruned_bytes(tmp_path: Path, pruned: bool) -> None:
    store, payload = SQLiteArtifactPayloadStore(tmp_path / "db"), _payload()
    stored = store.store_payload(payload)
    path = store._stored_payload_path(stored)
    if pruned:
        store.prune_payload(stored.artifact_id)
    else:
        path.unlink()
    for publish in (store.store_payload, store.store_payload_immutable):
        with pytest.raises((ValueError, FileNotFoundError)):
            publish(payload, artifact_id=stored.artifact_id)
    assert not path.exists()
