"""Locked phase-local reads, not a public authorization cache or cross-phase proof."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agent_storage.postgres.coverage_artifacts import read_artifact
from agent_storage.postgres.coverage_model_checkpoint import _CheckpointBodies
from zebra_agent_worker import coverage_proof_reads as module

from tests.worker.test_coverage_verified_reads import fixture


@pytest.fixture
def proof(monkeypatch):
    source, record, authority = fixture()
    connection = object()
    rows = Mock(side_effect=lambda *args: deepcopy(record))
    monkeypatch.setattr(module, "lock_payload", rows)
    monkeypatch.setattr(module, "artifact_payload_from_row", lambda row: row)
    return source, record, authority, connection, rows


def read(reader, record):
    return read_artifact(reader, record.uri, record.reservation.sha256, record.session_id)


def test_pure_cache_gets_use_native_rows_but_one_entry_exit_authority(proof):
    source, record, authority, connection, rows = proof
    with source._locked_proof_scope(connection, source.deployment, source.binding) as reader:
        bodies = _CheckpointBodies(reader)
        for _ in range(3):
            assert read(bodies, record) == b"{}"
        assert authority.call_count == 3  # Entry + physical pre/post, no exit yet.
        assert rows.call_count >= 6
        for call in rows.call_args_list:
            assert call.args == (
                connection, source.deployment, record.artifact_id, record.session_id,
            )
    assert authority.call_count == 4
    source.metadata.get_metadata.assert_not_called()
    source.objects.read_version_verified.assert_called_once()
    with pytest.raises(RuntimeError, match="ended"):
        read(bodies, record)
    with source._locked_proof_scope(connection, source.deployment, source.binding) as reader:
        assert read(_CheckpointBodies(reader), record) == b"{}"
    assert source.objects.read_version_verified.call_count == 2  # New phase rereads.


@pytest.mark.parametrize("final", [False, True])
def test_known_pure_deriver_reuses_locked_full_record_only_in_this_scope(proof, final):
    from agent_integrations.coverage_model_derivation import derive_semantic_observation

    source, record, authority, connection, rows = proof
    for phase in range(2):
        with source._locked_proof_scope(
            connection, source.deployment, source.binding, derive=derive_semantic_observation,
            final_certification=final,
        ) as reader:
            bodies = _CheckpointBodies(reader)
            for _ in range(3):
                assert read(bodies, record) == b"{}"
            assert rows.call_count == phase + 1
    assert authority.call_count == 4  # Each pure phase has an entry and exit guard.
    assert source.objects.read_version_verified.call_count == 2


def test_unknown_deriver_does_not_enable_record_reuse(proof):
    source, record, _, connection, rows = proof
    with source._locked_proof_scope(
        connection, source.deployment, source.binding, derive=lambda *_: None
    ) as reader:
        bodies = _CheckpointBodies(reader)
        read(bodies, record)
        before = rows.call_count
        read(bodies, record)
        assert rows.call_count > before


def test_native_pins_share_record_and_reject_foreign_or_escaped_transaction(proof):
    from agent_integrations.coverage_model_derivation import derive_semantic_observation

    source, record, _, connection, rows = proof
    with source._locked_proof_scope(
        connection, source.deployment, source.binding, derive=derive_semantic_observation,
    ) as reader:
        assert read(reader, record) == b"{}"
        for _ in range(3):
            reader._native_payload_row(
                connection, source.deployment, record.artifact_id, record.session_id,
            )
        assert rows.call_count == 1
        for conn, deployment, session in (
            (object(), source.deployment, record.session_id),
            (connection, "foreign", record.session_id),
            (connection, source.deployment, "foreign"),
        ):
            with pytest.raises(ValueError, match="identity conflicts"):
                reader._native_payload_row(conn, deployment, record.artifact_id, session)
        assert rows.call_count == 1
    assert not reader._proof_rows
    with pytest.raises(RuntimeError, match="ended"):
        reader._native_payload_row(
            connection, source.deployment, record.artifact_id, record.session_id,
        )


def test_incremental_pure_phase_reuses_bytes_but_final_certification_rereads(proof):
    from agent_integrations.coverage_model_derivation import derive_semantic_observation

    source, record, authority, connection, rows = proof
    source.reuse_verified_payloads = True
    assert read(source, record) == b"{}"
    source.objects.read_version_verified.assert_called_once()
    before = authority.call_count
    with source._locked_proof_scope(
        connection, source.deployment, source.binding, derive=derive_semantic_observation,
    ) as reader:
        assert read(reader, record) == b"{}"
        assert read(reader, record) == b"{}"
        assert rows.call_count == 1
    assert authority.call_count == before + 2  # Entry/exit, no external I/O in between.
    assert source.objects.read_version_verified.call_count == 1
    for _ in range(2):
        with source._locked_proof_scope(
            connection, source.deployment, source.binding, derive=derive_semantic_observation,
            final_certification=True,
        ) as reader:
            assert read(reader, record) == b"{}"
    assert source.objects.read_version_verified.call_count == 3


def test_arbitrary_final_deriver_cannot_reuse_incremental_bytes(proof):
    source, record, _, connection, _ = proof
    source.reuse_verified_payloads = True
    assert read(source, record) == b"{}"
    with source._locked_proof_scope(
        connection, source.deployment, source.binding, derive=lambda *_: None,
        final_certification=True,
    ) as reader:
        assert read(reader, record) == b"{}"
    assert source.reuse_verified_payloads
    assert source.objects.read_version_verified.call_count == 2


@pytest.mark.parametrize("boundary", ["entry", "physical_pre", "physical_post", "exit"])
def test_unknown_deriver_revocation_refuses_at_each_observable_boundary(proof, boundary):
    source, record, authority, connection, _ = proof
    fail_at = {"entry": 1, "physical_pre": 2, "physical_post": 3, "exit": 4}[boundary]
    authority.side_effect = [None] * (fail_at - 1) + [ValueError("revoked")]
    escaped = None
    with pytest.raises(ValueError, match="revoked"):
        with source._locked_proof_scope(
            connection, source.deployment, source.binding,
        ) as reader:
            escaped = reader
            assert read(_CheckpointBodies(reader), record) == b"{}"
    assert source.objects.read_version_verified.call_count == (fail_at >= 3)
    if escaped is not None:
        with pytest.raises(RuntimeError, match="ended"):
            escaped.get_payload(record.artifact_id)


@pytest.mark.parametrize("final", [False, True])
def test_pure_phase_revoked_during_original_read_never_returns_success(proof, final):
    from agent_integrations.coverage_model_derivation import derive_semantic_observation

    source, record, authority, connection, _ = proof
    revoked = False

    def check():
        if revoked:
            raise ValueError("revoked during original read")

    def original(*_):
        nonlocal revoked
        revoked = True
        return b"{}"

    authority.side_effect = check
    source.objects.read_version_verified.side_effect = original
    with pytest.raises(ValueError, match="revoked during original read"):
        with source._locked_proof_scope(
            connection, source.deployment, source.binding, derive=derive_semantic_observation,
            final_certification=final,
        ) as reader:
            assert read(reader, record) == b"{}"  # Internal only; exit must refuse.
    assert authority.call_count == 2
    assert not reader._proof_records and not reader._proof_rows
    with pytest.raises(RuntimeError, match="ended"):
        read(reader, record)


@pytest.mark.parametrize("damage", ["version", "kind", "expired", "deleted"])
def test_cached_bytes_never_bypass_full_native_metadata_or_time(proof, damage):
    source, record, _, connection, rows = proof
    with source._locked_proof_scope(connection, source.deployment, source.binding) as reader:
        bodies = _CheckpointBodies(reader)
        read(bodies, record)
        changed = deepcopy(record)
        if damage == "version":
            changed.object_receipt.object_version = "v2"
        elif damage == "kind":
            changed.reservation.kind = "other"
        elif damage == "expired":
            changed.reservation.retained_until = datetime.now(UTC) - timedelta(seconds=1)
        else:
            rows.side_effect = ValueError("deleted")
        if damage != "deleted":
            rows.side_effect = lambda *args: deepcopy(changed)
        with pytest.raises(ValueError):
            read(bodies, record)
        source.objects.read_version_verified.assert_called_once()


def test_scope_mismatch_and_publish_are_denied(proof):
    source, record, authority, connection, _ = proof
    with pytest.raises(ValueError, match="scope conflicts"):
        with source._locked_proof_scope(connection, "other", source.binding):
            pytest.fail("entered mismatched deployment")
    with pytest.raises(ValueError, match="scope conflicts"):
        with source._locked_proof_scope(connection, source.deployment, SimpleNamespace()):
            pytest.fail("entered mismatched binding")
    authority.assert_not_called()
    with source._locked_proof_scope(connection, source.deployment, source.binding) as reader:
        with pytest.raises(ValueError, match="cannot publish"):
            reader.store_payload_immutable(None, artifact_id=record.artifact_id)
    source.publisher.materialize.assert_not_called()


def test_metadata_capacity_falls_back_without_new_commit_eligibility_limit(proof):
    source, record, authority, connection, _ = proof
    with source._locked_proof_scope(connection, source.deployment, source.binding) as reader:
        reader._proof_records.update(dict.fromkeys(range(8192)))
        bodies = _CheckpointBodies(reader)
        for _ in range(2):
            assert read(bodies, record) == b"{}"
        assert len(reader._proof_records) == 8192
        assert record.artifact_id not in reader._proof_records
        assert authority.call_count > 3
        assert source.metadata.get_metadata.call_count >= 4
    source.objects.read_version_verified.assert_called_once()


@pytest.mark.parametrize("reuse", [False, True])
@pytest.mark.parametrize("final", [False, True])
def test_time_is_rechecked_without_metadata_change(proof, monkeypatch, reuse, final):
    from agent_integrations.coverage_model_derivation import derive_semantic_observation
    from zebra_agent_worker import coverage_artifacts

    source, record, _, connection, _ = proof
    with source._locked_proof_scope(
        connection, source.deployment, source.binding,
        derive=derive_semantic_observation if reuse else None,
        final_certification=final,
    ) as reader:
        bodies = _CheckpointBodies(reader)
        read(bodies, record)
        later = record.reservation.retained_until + timedelta(seconds=1)
        monkeypatch.setattr(module, "datetime", SimpleNamespace(now=lambda *_: later))
        monkeypatch.setattr(coverage_artifacts, "datetime", SimpleNamespace(now=lambda *_: later))
        with pytest.raises(ValueError):
            read(bodies, record)
        source.objects.read_version_verified.assert_called_once()


@pytest.mark.parametrize("incremental,rebuild", [(True, False), (False, False), (True, True)])
def test_scope_composition_keeps_eager_compatibility_and_exit_before_return(
    monkeypatch, incremental, rebuild
):
    from agent_storage.postgres import coverage_model_acceptance as acceptance
    from agent_storage.postgres import coverage_model_verification as verification

    phases = []
    connection, binding, reader = object(), object(), object()

    @contextmanager
    def scope(*args, **kwargs):
        assert args == (connection, "deployment", binding)
        assert kwargs == {"derive": None}
        phases.append("entry")
        yield reader
        phases.append("exit")

    original = SimpleNamespace(_locked_proof_scope=scope)
    expected = reader if incremental and not rebuild else original

    def verifier(*args, **kwargs):
        assert kwargs["artifacts"] is expected
        assert kwargs["_commit_results"] == (() if incremental else None)
        phases.append("verify")
        return SimpleNamespace(verify=lambda *_, **__: "eager-policy")

    monkeypatch.setattr(verification, "_ModelVerification", verifier)
    result = acceptance.verify_model_results(
        connection, "deployment", binding, (), artifacts=original,
        derive=None, deadlines=[], incremental_commit=incremental, rebuild=rebuild,
    )
    assert result == "eager-policy"
    assert phases == (["entry", "verify", "exit"] if incremental and not rebuild else ["verify"])


def test_final_scope_unknown_deriver_retains_original_guarded_reader(proof):
    source, record, authority, connection, rows = proof
    with source._locked_proof_scope(
        connection, source.deployment, source.binding, final_certification=True,
        derive=lambda *_: None,
    ) as reader:
        assert reader is source
        read(reader, record)
    rows.assert_not_called()
    assert authority.call_count >= 2
    assert source.metadata.get_metadata.call_count >= 2


def test_independent_final_scope_physically_refuses_corrupted_object(proof):
    from agent_integrations.coverage_model_derivation import derive_semantic_observation

    source, record, _, connection, rows = proof
    with source._locked_proof_scope(
        connection, source.deployment, source.binding, final_certification=True,
        derive=derive_semantic_observation,
    ) as reader:
        assert read(_CheckpointBodies(reader), record) == b"{}"
    source.objects.read_version_verified.side_effect = ValueError("corrupt object")
    with pytest.raises(ValueError, match="corrupt object"):
        with source._locked_proof_scope(
            connection, source.deployment, source.binding, final_certification=True,
            derive=derive_semantic_observation,
        ) as reader:
            read(_CheckpointBodies(reader), record)
    assert rows.call_count == 2
    assert source.objects.read_version_verified.call_count == 2
    assert reader._proof_connection is None
