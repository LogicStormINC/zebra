"""Bounded normal receipt read, legacy fallback and native mutation refusal."""
# ruff: noqa: F811

import pytest
from agent_storage.postgres import coverage as storage
from agent_storage.postgres import coverage_execution_receipt_read as reader
from agent_storage.postgres import coverage_execution_receipts as writer
from agent_storage.postgres.coverage_recovery_preparation import RecoveryReadSnapshot

from tests.worker.test_coverage_execution_receipts import (  # noqa: F401
    NAMESPACE,
    dsn,
    model_cloud,
    native_worker,
    postgres_dsn,
    receipt_composition,
    receipt_protocol,
    run,
)


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
@pytest.mark.parametrize("legacy", [False, True])
def test_receipt_revision_read_is_bounded_and_legacy_remains_exact(
    native_worker, monkeypatch, legacy,
):
    env = native_worker
    mint = storage.mint_execution_receipt
    fingerprint = reader.model_fingerprint
    scans = []
    if legacy:
        monkeypatch.setattr(writer, "model_revision", lambda *args: None)

    def scan(*args):
        scans.append(1)
        assert legacy, "normal receipt must not rescan MODEL history"
        return fingerprint(*args)

    monkeypatch.setattr(reader, "model_fingerprint", scan)
    monkeypatch.setattr(writer, "model_fingerprint", scan)

    class ProbeFinished(BaseException):
        pass

    def probe(connection, deployment, binding, event, facts, **kwargs):
        mint(connection, deployment, binding, event, facts, **kwargs)
        body = connection.execute(
            "SELECT body FROM coverage_execution_receipts WHERE event_id=%s",
            (event.event_id,),
        ).fetchone()["body"]
        assert (body["model_fingerprint"] is not None) == legacy
        assert (body["model_revision"] is None) == legacy
        before = list(env.client.calls)
        snapshot = RecoveryReadSnapshot(connection)
        receipt = reader.read_execution_receipt(snapshot, deployment, binding)
        assert receipt is not None
        assert len(snapshot.reads) == 2
        assert bool(scans) == legacy
        snapshot.revalidate(connection)
        if not legacy:
            with monkeypatch.context() as missing_root:
                missing_root.setattr(reader, "model_revision", lambda *args: None)
                with pytest.raises(ValueError, match="native model source"):
                    reader.read_execution_receipt(connection, deployment, binding)
            assert not scans  # Missing root must not downgrade to legacy validation.
        # Fresh mutation tracking covers each representation, not just new Events.
        for table, assignment in (
            ("coverage_model_events", "event_digest=repeat('0',64)"),
            ("coverage_model_calls", "reserved_sequence=reserved_sequence+1"),
            ("coverage_model_ledger", "charged_tokens=charged_tokens+1"),
        ):
            class RollbackProbe(Exception):
                pass

            with pytest.raises(RollbackProbe), connection.transaction():
                connection.execute(f"UPDATE {table} SET {assignment}")
                with pytest.raises(ValueError, match="native model source"):
                    reader.read_execution_receipt(connection, deployment, binding)
                raise RollbackProbe
            assert reader.read_execution_receipt(connection, deployment, binding) == receipt
        assert env.client.calls == before
        raise ProbeFinished

    monkeypatch.setattr(storage, "mint_execution_receipt", probe)
    with pytest.raises(ProbeFinished):
        run(env)
