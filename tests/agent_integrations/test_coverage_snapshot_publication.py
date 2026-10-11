"""Real SQLite publication, shared-lock concurrency and corrupt-ID refusal."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier, Event
from urllib.parse import unquote, urlsplit

import pytest
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_integrations.coverage_snapshot import HostCoverageSnapshotAdapter

from tests.agent_integrations.test_coverage_snapshot import AUTHORITY, NOW, setup_adapter


def test_fresh_adapters_share_publication_lock_real_sqlite(tmp_path, monkeypatch):
    adapter, host, store, options = setup_adapter(tmp_path)
    writers = 0
    original = store.store_payload_immutable

    def counted(*args, **kwargs):
        nonlocal writers
        writers += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "store_payload_immutable", counted)
    gate = Barrier(2)

    def publish():
        fresh = HostCoverageSnapshotAdapter(**options)
        gate.wait(timeout=5)
        return fresh.get("snapshot", authority=AUTHORITY)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = tuple(executor.map(lambda _: publish(), range(2)))
    assert first == second and writers == 1
    assert adapter.get("snapshot", authority=AUTHORITY) == first
    assert host.records


def test_publish_rechecks_corrupt_deterministic_id_under_lock(tmp_path, monkeypatch):
    adapter, _, store, _ = setup_adapter(tmp_path)
    snapshot = adapter.get("snapshot", authority=AUTHORITY)
    identifier = adapter.manifest_artifact_id(snapshot)
    path = Path(unquote(urlsplit(store.get_payload(identifier).access_uri).path))
    path.write_bytes(b"corrupt deterministic artifact")

    def no_write(*args, **kwargs):
        pytest.fail("existing corrupt deterministic artifact must never reach store_payload")

    monkeypatch.setattr(store, "store_payload_immutable", no_write)
    with pytest.raises(CoverageRefusedError, match="artifact_unavailable"):
        adapter.artifacts.publish(
            identifier,
            "coverage_manifest",
            b"replacement",
            33554432,
            lambda: NOW,
            snapshot.expires_at,
        )
    assert path.read_bytes() == b"corrupt deterministic artifact"


def test_publication_conflict_leaves_existing_valid_payload(tmp_path, monkeypatch):
    adapter, _, store, _ = setup_adapter(tmp_path)
    snapshot = adapter.get("snapshot", authority=AUTHORITY)
    identifier = adapter.manifest_artifact_id(snapshot)
    original = store.read_payload_bytes(identifier)

    def no_write(*args, **kwargs):
        pytest.fail("different bytes at an existing ID must never be overwritten")

    monkeypatch.setattr(store, "store_payload_immutable", no_write)
    with pytest.raises(CoverageRefusedError, match="artifact_unavailable"):
        adapter.artifacts.publish(
            identifier,
            "coverage_manifest",
            b"different",
            33554432,
            lambda: NOW,
            snapshot.expires_at,
        )
    assert store.read_payload_bytes(identifier) == original


def test_budget_rechecked_after_waiting_for_publication_lock(tmp_path, monkeypatch):
    tick = [0.0]
    adapter, _, store, options = setup_adapter(tmp_path, monotonic=lambda: tick[0], max_seconds=1)
    budget = adapter.host.budget(AUTHORITY)
    started = Event()
    snapshot = adapter.get("snapshot", authority=AUTHORITY)
    manifest_id = adapter.manifest_artifact_id(snapshot)

    def no_write(*args, **kwargs):
        pytest.fail("expired operation must not write after lock acquisition")

    monkeypatch.setattr(store, "store_payload_immutable", no_write)

    def publish():
        started.set()
        return adapter.artifacts.publish(
            manifest_id,
            "coverage_manifest",
            b"new",
            33554432,
            lambda: adapter.host.publication_time(
                AUTHORITY, budget, NOW, NOW + timedelta(minutes=1)
            ),
            NOW + timedelta(minutes=1),
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        with options["publication_lock"]:
            pending = executor.submit(publish)
            assert started.wait(timeout=5)
            tick[0] = 2.0
        with pytest.raises(CoverageRefusedError, match="budget_exceeded"):
            pending.result(timeout=5)


@pytest.mark.parametrize("mutation", ["metadata", "prune", "delete_metadata", "missing_file"])
def test_load_refuses_mutation_between_bytes_and_inspection(tmp_path, monkeypatch, mutation):
    adapter, _, store, _ = setup_adapter(tmp_path)
    snapshot = adapter.get("snapshot", authority=AUTHORITY)
    identifier = adapter.manifest_artifact_id(snapshot)
    original_read = store.read_payload_bytes_bounded
    read_ids = []

    def mutate_after_read(artifact_id, *, max_bytes):
        body = original_read(artifact_id, max_bytes=max_bytes)
        read_ids.append(artifact_id)
        if mutation == "prune":
            store.prune_payload(artifact_id)
        elif mutation == "missing_file":
            path = Path(unquote(urlsplit(store.get_payload(artifact_id).access_uri).path))
            path.unlink()
        else:
            with sqlite3.connect(tmp_path / "artifacts.sqlite") as connection:
                if mutation == "metadata":
                    connection.execute(
                        "UPDATE artifact_payloads SET kind = 'changed' WHERE artifact_id = ?",
                        (str(artifact_id),),
                    )
                else:
                    connection.execute(
                        "DELETE FROM artifact_payloads WHERE artifact_id = ?", (str(artifact_id),)
                    )
        return body

    monkeypatch.setattr(store, "read_payload_bytes_bounded", mutate_after_read)
    with pytest.raises(CoverageRefusedError, match="artifact_unavailable"):
        adapter.artifacts.load(identifier, "coverage_manifest", 33554432, adapter.host.now())
    assert read_ids == [identifier]
