"""Pure proof coalescing stops at physical I/O, revocation and final native time."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from agent_core.domain.identifiers import ArtifactId
from agent_integrations.coverage_model_derivation import derive_semantic_observation
from agent_storage.postgres.coverage_artifacts import read_artifact
from zebra_agent_worker import coverage_proof_reads as module

from tests.worker.test_coverage_verified_reads import fixture


@pytest.mark.parametrize("reader_kind", ["locked", "prepared"])
@pytest.mark.parametrize("cache_mismatch", [False, True])
def test_revocation_during_object_one_refuses_before_object_two(
    monkeypatch,
    reader_kind,
    cache_mismatch,
):
    source, record, authority = fixture()
    second = deepcopy(record)
    second.artifact_id = ArtifactId(uuid4())
    second.uri = f"artifact://{second.artifact_id}"
    records = {row.artifact_id: row for row in (record, second)}
    monkeypatch.setattr(module, "lock_payload", lambda *args: deepcopy(records[args[2]]))
    monkeypatch.setattr(module, "artifact_payload_from_row", lambda row: row)
    revoked = False

    def check():
        if revoked:
            raise ValueError("revoked")

    def original(*args):
        nonlocal revoked
        revoked = True
        return b"{}"

    authority.side_effect = check
    source.objects.read_version_verified.side_effect = original
    if cache_mismatch:
        source.reuse_verified_payloads = True
        old = deepcopy(record)
        old.object_receipt.object_version = "old-version"
        source._verified_payloads[record.artifact_id] = old, b"{}"
        source._verified_bytes = 2
    if reader_kind == "prepared":
        from zebra_agent_worker import coverage_prepared_reads as prepared

        def metadata_batch(current, _):
            current.check_authority()
            return deepcopy(records)

        monkeypatch.setattr(prepared, "metadata_batch", metadata_batch)
        context = prepared.prepared_reads(source, tuple(records))
    else:
        context = source._locked_proof_scope(
            object(),
            source.deployment,
            source.binding,
            derive=derive_semantic_observation,
        )
    with pytest.raises(ValueError, match="revoked"):
        with context as reader:
            for row in (record, second):
                read_artifact(reader, row.uri, row.reservation.sha256, row.session_id)
    source.objects.read_version_verified.assert_called_once()
    assert reader._proof_connection is None if reader_kind == "locked" else reader._records is None


def test_lifecycle_only_cache_does_not_suppress_missing_event_prefetch(monkeypatch):
    source, record, _ = fixture()
    connection = object()
    monkeypatch.setattr(module, "artifact_payload_from_row", lambda row: row)
    row = {"event_id": uuid4()}
    monkeypatch.setattr(module, "lock_payload", lambda *_: row)
    page = Mock(return_value=({record.artifact_id: row}, []))
    monkeypatch.setattr(module, "locked_page", page)
    with source._locked_proof_scope(
        connection,
        source.deployment,
        source.binding,
        derive=derive_semantic_observation,
    ) as reader:
        reader._native_payload_row(
            connection, source.deployment, record.artifact_id, record.session_id
        )
        assert record.artifact_id in reader._proof_rows
        assert record.artifact_id not in reader._proof_events
        reader._prefetch_proof((record.artifact_id,))
        page.assert_called_once()
        assert reader._proof_events[record.artifact_id] == []
        reader._prefetch_proof((record.artifact_id,))
        page.assert_called_once()


@pytest.mark.parametrize("expired", [False, True])
def test_pure_retention_uses_earliest_deadline_after_exit_callback(monkeypatch, expired):
    source, _, authority = fixture()
    connection = Mock()
    connection.info = None
    now = datetime.now(UTC)
    deadline = now + timedelta(seconds=1)
    native_now = now

    def clock():
        nonlocal native_now
        if authority.call_count == 2:  # The final extensible authority callback.
            native_now = deadline if expired else now

    authority.side_effect = clock
    connection.execute.return_value.fetchone.side_effect = lambda: {"now": native_now}
    context = source._locked_proof_scope(
        connection,
        source.deployment,
        source.binding,
        derive=derive_semantic_observation,
    )

    def run():
        with context as reader:
            for value in (deadline + timedelta(seconds=10), deadline, deadline):
                assert reader._defer_checkpoint_retention(connection, [value])
            connection.execute.assert_not_called()
            assert reader._proof_deadlines == [deadline]
            with pytest.raises(ValueError, match="identity"):
                reader._defer_checkpoint_retention(object(), [deadline])
        return reader

    if expired:
        with pytest.raises(ValueError, match="retention expired"):
            run()
    else:
        reader = run()
        assert not reader._proof_deadlines
        with pytest.raises(RuntimeError, match="ended"):
            reader._defer_checkpoint_retention(connection, [deadline])
    connection.execute.assert_called_once_with("SELECT clock_timestamp() AS now")


def test_unknown_callback_cannot_defer_native_retention_clock():
    source, _, _ = fixture()
    connection = object()
    with source._locked_proof_scope(connection, source.deployment, source.binding) as reader:
        assert not reader._defer_checkpoint_retention(connection, [datetime.now(UTC)])
        assert not reader._proof_deadlines
