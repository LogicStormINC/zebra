"""Bounded pages, exact disk-spooled source comparison and private byte reuse."""

from pickle import dump
from tempfile import TemporaryFile
from types import SimpleNamespace
from uuid import UUID

import pytest
from agent_core.domain.coverage_model_checkpoint import MODEL_CHECKPOINT_KIND
from agent_storage.postgres.coverage import PostgresCoverageStore
from agent_storage.postgres.coverage_model_checkpoint import _CheckpointBodies
from agent_storage.postgres.coverage_model_replay_rows import (
    indexed_calls,
    model_rows,
    original_rows,
)
from agent_storage.postgres.coverage_transactions import iter_run_events


@pytest.mark.parametrize("count", [0, 1, 100, 101, 1000])
def test_exact_run_pages_equal_sequences_and_fixed_upper_boundary(count):
    rows = [{"sequence": i // 2, "event_id": UUID(int=i + 1)} for i in range(count)]
    pages = []

    class Connection:
        def execute(self, sql, params):
            if "max(sequence)" in sql:
                return SimpleNamespace(
                    fetchone=lambda: {"last": rows[-1]["sequence"] if rows else None}
                )
            assert "LIMIT 100" in sql and "FOR SHARE" in sql
            upper, sequence, identifier = params[-3:]
            selected = [
                row
                for row in rows
                if row["sequence"] <= upper
                and (
                    row["sequence"] > sequence
                    or (row["sequence"] == sequence and row["event_id"] > identifier)
                )
            ][:100]
            pages.append(len(selected))
            return SimpleNamespace(fetchall=lambda: selected)

    assert list(iter_run_events(Connection(), "d", "n", "r", locked=True)) == rows
    assert max(pages, default=0) <= 100


@pytest.mark.parametrize("change", ["payload", "insert", "delete", "unchanged"])
def test_disk_spool_comparison_refuses_any_full_row_difference(monkeypatch, change):
    source = [{"sequence": 1, "payload": {"private": "one"}}, {"sequence": 2}]
    current = [dict(row) for row in source]
    if change == "payload":
        current[0]["payload"] = {"private": "changed"}
    elif change == "insert":
        current.append({"sequence": 3})
    elif change == "delete":
        current.pop()
    import agent_storage.postgres.coverage as coverage

    monkeypatch.setattr(coverage, "iter_run_events", lambda *a, **k: iter(current))
    store = object.__new__(PostgresCoverageStore)
    store._deployment = "d"
    with TemporaryFile() as spool:
        for row in source:
            dump(row, spool)
        if change == "unchanged":
            store._assert_rebuild_source(None, "n", "r", spool)
        else:
            with pytest.raises(ValueError, match="Events changed"):
                store._assert_rebuild_source(None, "n", "r", spool)


def test_private_checkpoint_bytes_reuse_does_not_cache_metadata_or_cross_phase(monkeypatch):
    import agent_storage.postgres.coverage_artifacts as artifacts

    reads = []
    metadata = SimpleNamespace(kind=MODEL_CHECKPOINT_KIND, size_bytes=3)

    class Reader:
        def get_payload(self, identifier):
            return metadata

        def read_payload_bytes_bounded(self, identifier, *, max_bytes):
            reads.append(identifier)
            return b"abc"

    reader = Reader()
    cached = _CheckpointBodies(reader)
    for _ in range(3):
        assert cached.read_payload_bytes_bounded("one", max_bytes=3) == b"abc"
    assert reads == ["one"]
    with pytest.raises(ValueError, match="bound changed"):
        cached.read_payload_bytes_bounded("one", max_bytes=2)
    monkeypatch.setattr(artifacts, "MAX_COVERAGE_ARTIFACT_BYTES", 3)
    with pytest.raises(ValueError, match="cumulative read bound"):
        cached.read_payload_bytes_bounded("two", max_bytes=3)
    assert reads == ["one"]
    metadata = SimpleNamespace(kind=MODEL_CHECKPOINT_KIND, size_bytes=3, revision=2)
    with pytest.raises(ValueError, match="metadata/byte bound changed"):
        cached.read_payload_bytes_bounded("one", max_bytes=3)
    assert _CheckpointBodies(reader).read_payload_bytes_bounded("one", max_bytes=3) == b"abc"
    assert reads == ["one", "one"]


@pytest.mark.parametrize("mode", ["source", "index"])
def test_model_history_and_call_index_are_paged_not_materialized(mode):
    rows = [{"sequence": i, "reservation_key": f"key-{i:04}",
             "event_type": "coverage_model_call_reserved"} for i in range(301)]
    pages = []
    binding = SimpleNamespace(namespace="n", run_id="r", session_id="s")

    class Connection:
        def execute(self, sql, params):
            if "max(sequence)" in sql:
                return SimpleNamespace(fetchone=lambda: {"last": 300})
            assert "LIMIT 100" in sql
            cursor = params[-1]
            key = "sequence" if mode == "source" else "reservation_key"
            selected = [row for row in rows if row[key] > cursor][:100]
            pages.append(len(selected))
            return SimpleNamespace(fetchall=lambda: selected)

    result = (
        model_rows(Connection(), "d", binding, ())
        if mode == "source"
        else indexed_calls(Connection(), "d", binding)
    )
    assert list(result) == rows
    assert pages == [100, 100, 100, 1]  # Pinned short pages are exhaustive in both paths.


def test_original_pages_use_recorded_execute_and_fixed_upper():
    rows = [{"sequence": index} for index in range(302)]
    pages = []

    class Connection:
        def execute(self, sql, parameters):
            assert "LIMIT 100" in sql
            cursor, upper = parameters[-2:]
            selected = [row for row in rows if cursor < row["sequence"] <= upper][:100]
            pages.append(len(selected))
            return SimpleNamespace(fetchall=lambda: selected)

    assert list(original_rows(Connection(), "sql", (), 300)) == rows[:301]
    assert pages == [100, 100, 100, 1]


@pytest.mark.parametrize("count", [0, 1, 100, 101, 1000])
def test_original_pages_are_lazy_and_stop_at_proven_upper(count):
    rows = [{"sequence": index} for index in range(count + 1)]
    queries = []

    class Connection:
        def execute(self, sql, parameters):
            cursor, upper = parameters[-2:]
            queries.append((cursor, upper))
            selected = [row for row in rows if cursor < row["sequence"] <= upper][:100]
            return SimpleNamespace(fetchall=lambda: selected)

    result = original_rows(Connection(), "sql", (), count - 1)
    assert queries == []
    if count:
        assert next(result) == rows[0]
        assert len(queries) == 1  # Consumer demand fetches only the first bounded page.
        assert [rows[0], *result] == rows[:count]
    else:
        assert list(result) == []
    assert len(queries) == (count + 99) // 100


def test_original_pages_cannot_bypass_expired_recovery_deadline():
    from time import monotonic

    from agent_storage.postgres.coverage_recovery_preparation import (
        CoverageRecoveryDeferred,
        RecoveryDeadlineConnection,
    )

    class Connection:
        def execute(self, *args):
            pytest.fail("expired deadline must refuse before database I/O")

    with pytest.raises(CoverageRecoveryDeferred):
        list(original_rows(RecoveryDeadlineConnection(Connection(), monotonic() - 1), "sql", (), 1))


def test_original_pages_are_recorded_for_recovery_revalidation():
    from agent_storage.postgres.coverage_recovery_preparation import RecoveryReadSnapshot

    class Connection:
        def execute(self, sql, parameters):
            selected = [{"sequence": 1}] if parameters[-2] == -1 else []
            return SimpleNamespace(fetchall=lambda: selected)

    snapshot = RecoveryReadSnapshot(Connection())
    assert list(original_rows(snapshot, "SELECT 1 AS sequence", (), 1)) == [{"sequence": 1}]
    assert len(snapshot.reads) == 1
    snapshot.revalidate(Connection())


@pytest.mark.parametrize("damage", ["duplicate_join", "missing_metadata", "byte_bound"])
def test_original_preflight_refuses_aggregate_damage_before_paging(damage):
    from agent_storage.postgres.coverage_model_source import preflight_original_volume

    sizes = {"count": 2, "unique_count": 2, "available": 2, "bytes": 2, "last": 2}
    if damage == "duplicate_join":
        sizes["unique_count"] = 1
    elif damage == "missing_metadata":
        sizes["available"] = 1
    else:
        sizes["bytes"] = 33 * 1024 * 1024

    class Connection:
        calls = 0

        def execute(self, sql, parameters):
            self.calls += 1
            assert self.calls <= 2, "damage must refuse before any original-page/lifecycle read"
            result = {"count": 2, "bytes": 2} if self.calls == 1 else sizes
            return SimpleNamespace(fetchone=lambda: result)

    with pytest.raises(ValueError):
        preflight_original_volume(
            Connection(), "d", SimpleNamespace(session_id="s", namespace="n", run_id="r")
        )
