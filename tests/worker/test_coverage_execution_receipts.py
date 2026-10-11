"""Native PG/Worker receipts; Host/model/S3 transports remain controlled fixtures."""
# ruff: noqa: F811

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import psycopg
import pytest
from agent_core.domain.coverage_contracts import coverage_digest
from agent_core.domain.events import EventType, SessionEvent
from agent_storage.postgres import coverage as coverage_store
from agent_storage.postgres.coverage_execution_receipt_read import read_execution_receipt
from agent_storage.postgres.coverage_execution_receipts import model_fingerprint
from agent_storage.postgres.coverage_recovery_preparation import RecoveryReadSnapshot
from psycopg.types.json import Jsonb
from zebra_agent_config.coverage_settings import CoverageWorkSettings

from tests.worker.coverage_model_cloud_fixtures import (  # noqa: F401
    NAMESPACE,
    dsn,
    model_cloud,
    postgres_dsn,
)
from tests.worker.test_coverage_dispatch import native_handoff, native_worker  # noqa: F401


@pytest.fixture
def receipt_protocol(request):
    return getattr(request, "param", True)


@pytest.fixture(autouse=True)
def receipt_composition(monkeypatch, receipt_protocol):
    """Explicit trusted test composition; production routing remains unchanged."""
    original = coverage_store.PostgresCoverageStore.__init__

    def configured(store, *args, **kwargs):
        if receipt_protocol:
            kwargs = kwargs | {"execution_receipts": True}
        else:
            assert "execution_receipts" not in kwargs  # Protect the constructor default itself.
        original(store, *args, **kwargs)

    monkeypatch.setattr(coverage_store.PostgresCoverageStore, "__init__", configured)


def run(env):
    env.reply_from_request = True
    env.service._settings = replace(
        env.service._settings, coverage_work=CoverageWorkSettings(max_milliseconds=60000),
    )
    handoff = native_handoff(env)
    return env.service.execute_claimed_session(handoff.lease, lease_ttl_seconds=300)


def rows(env):
    with env.database.connect() as connection:
        return connection.execute(
            """SELECT * FROM coverage_execution_receipts WHERE deployment_namespace=%s
               AND session_id=%s ORDER BY sequence""", (NAMESPACE, env.session),
        ).fetchall()


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
def test_native_receipt_chain_retry_and_append_only(native_worker, monkeypatch):
    env = native_worker
    original = coverage_store.PostgresCoverageStore.commit
    mint = coverage_store.mint_execution_receipt
    minted = 0
    read_counts = []

    def shorter_first(*args, **kwargs):
        nonlocal minted
        if minted == 0:
            kwargs["valid_until"] -= timedelta(seconds=1)
        minted += 1
        mint(*args, **kwargs)
        object_calls = list(env.client.calls)
        facts = read_execution_receipt(args[0], args[1], args[2])
        assert facts is not None and facts.event == args[3]
        snapshot = RecoveryReadSnapshot(args[0])
        assert read_execution_receipt(snapshot, args[1], args[2]) == facts
        assert len(snapshot.reads) == 2  # Source/chain + native fingerprint; clock stays fresh.
        snapshot.revalidate(args[0])
        if minted == 2:
            class RollbackPredecessor(Exception):
                pass

            with pytest.raises(RollbackPredecessor), args[0].transaction():
                args[0].execute("SET LOCAL session_replication_role=replica")
                args[0].execute(
                    """UPDATE session_events SET created_at=created_at+interval '1 microsecond'
                       WHERE event_type='coverage_batch_accepted' AND sequence<%s""",
                    (args[3].sequence,),
                )
                with pytest.raises(ValueError, match="predecessor conflicts"):
                    read_execution_receipt(args[0], args[1], args[2])
                raise RollbackPredecessor
        read_counts.append(facts.accepted_count)
        assert env.client.calls == object_calls

    def duplicate(store, request, *, fence):
        first = original(store, request, fence=fence)
        assert original(store, request, fence=fence) == first
        return first

    monkeypatch.setattr(coverage_store.PostgresCoverageStore, "commit", duplicate)
    monkeypatch.setattr(coverage_store, "mint_execution_receipt", shorter_first)
    run(env)
    receipts = rows(env)
    assert len(receipts) == 2
    assert minted == 2
    assert read_counts == [1, 2]
    assert receipts[1]["body"]["valid_until"] == receipts[0]["body"]["valid_until"]
    assert [row["body"]["accepted_count"] for row in receipts] == [1, 2]
    assert receipts[0]["predecessor_event_id"] is None
    assert receipts[1]["predecessor_event_id"] == receipts[0]["event_id"]
    assert receipts[1]["body"]["predecessor_digest"] == receipts[0]["body_digest"]
    for row in receipts:
        assert coverage_digest(row["body"]) == row["body_digest"]
        assert row["body"]["budget"]["unresolved"] == 0
        assert row["body"]["expected_count"] == 2
        assert row["body"]["command"]["receipt"]["wake_generation"] == 0
        assert row["body"]["accepted_event"]["event_id"] == str(row["event_id"])
    for statement in (
        "UPDATE coverage_execution_receipts SET body_digest=repeat('0',64)",
        "DELETE FROM coverage_execution_receipts",
        "TRUNCATE coverage_execution_receipts",
    ):
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            with env.database.connect() as connection:
                connection.execute(statement)
    for invalid in ({}, {"protocol": None}):
        with pytest.raises(psycopg.errors.CheckViolation):
            with env.database.connect() as connection:
                connection.execute(
                    """INSERT INTO coverage_execution_receipts
                       (deployment_namespace,namespace,run_id,session_id,event_id,sequence,
                        body,body_digest) SELECT deployment_namespace,namespace,run_id,
                        session_id,event_id,sequence,%s,body_digest
                       FROM coverage_execution_receipts LIMIT 1""", (Jsonb(invalid),),
                )


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
def test_mint_failure_rolls_back_native_acceptance_and_projection(native_worker, monkeypatch):
    env = native_worker
    original = coverage_store.mint_execution_receipt

    def abort(*args, **kwargs):
        original(*args, **kwargs)
        assert args[0].execute(
            "SELECT count(*) AS count FROM coverage_execution_receipts"
        ).fetchone()["count"] == 1
        raise ValueError("injected receipt transaction abort")

    monkeypatch.setattr(coverage_store, "mint_execution_receipt", abort)
    with pytest.raises(ValueError, match="injected receipt transaction abort"):
        run(env)
    assert rows(env) == []
    with env.database.connect() as connection:
        assert connection.execute("SELECT 1 FROM coverage_batches LIMIT 1").fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM coverage_units WHERE result IS NOT NULL LIMIT 1"
        ).fetchone() is None
    assert not any(
        event.event_type is EventType.COVERAGE_BATCH_ACCEPTED
        for event in env.events.list_for_session(env.session)
    )


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [600], indirect=True)
def test_eager_mode_does_not_mint_continuation_receipt(native_worker):
    run(native_worker)
    assert rows(native_worker) == []


@pytest.mark.parametrize("receipt_protocol", [False], indirect=True)
@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
def test_unqualified_composition_keeps_existing_path_without_mint(native_worker):
    run(native_worker)
    assert rows(native_worker) == []


@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
@pytest.mark.parametrize("table", ["coverage_model_events", "coverage_model_calls"])
def test_fingerprint_binds_witness_and_call_rows(model_cloud, table):
    from tests.worker.test_coverage_model_acceptance import settled

    env = model_cloud
    settled(env)
    with env.database.connect() as connection:
        before = model_fingerprint(connection, NAMESPACE, env.binding)
        connection.execute("DELETE FROM " + table)
        assert model_fingerprint(connection, NAMESPACE, env.binding) != before


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
@pytest.mark.parametrize("legacy", [False, True])
def test_receipt_capacity_falls_back_without_rejecting_legal_acceptance(
    native_worker, monkeypatch, legacy,
):
    if legacy:
        monkeypatch.setattr("agent_storage.postgres.coverage_execution_receipts.model_revision",
                            lambda *args: None)
    monkeypatch.setattr("agent_storage.postgres.coverage_execution_receipts.MAX_WITNESS_BYTES", 0)
    run(native_worker)
    # Fingerprint capacity is only a legacy constraint, not a version-root budget.
    assert len(rows(native_worker)) == (0 if legacy else 2)
    history = native_worker.events.list_for_session(native_worker.session)
    assert sum(event.event_type is EventType.COVERAGE_BATCH_ACCEPTED for event in history) == 2
    assert sum(event.event_type is EventType.COVERAGE_REPORT_CERTIFIED for event in history) == 1


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
def test_legacy_prefix_is_not_backfilled_from_projection(native_worker, monkeypatch):
    original = coverage_store.mint_execution_receipt
    calls = 0

    def legacy_first(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls > 1:
            original(*args, **kwargs)

    monkeypatch.setattr(coverage_store, "mint_execution_receipt", legacy_first)
    run(native_worker)
    assert calls == 2 and rows(native_worker) == []
    history = native_worker.events.list_for_session(native_worker.session)
    assert sum(event.event_type is EventType.COVERAGE_REPORT_CERTIFIED for event in history) == 1


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
def test_predecessor_native_source_mutation_refuses_and_rolls_back(native_worker, monkeypatch):
    original = coverage_store.mint_execution_receipt
    calls = 0

    def mutate(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            args[0].execute(
                """UPDATE session_events SET created_at=created_at+interval '1 microsecond'
                   WHERE event_type='coverage_batch_accepted' AND sequence<%s""",
                (args[3].sequence,),
            )
        original(*args, **kwargs)

    monkeypatch.setattr(coverage_store, "mint_execution_receipt", mutate)
    with pytest.raises(psycopg.errors.RaiseException, match="sources are sealed"):
        run(native_worker)
    assert calls == 2 and len(rows(native_worker)) == 1
    history = native_worker.events.list_for_session(native_worker.session)
    assert sum(event.event_type is EventType.COVERAGE_BATCH_ACCEPTED for event in history) == 1
    with native_worker.database.connect() as connection:
        surviving = connection.execute(
            "SELECT * FROM session_events WHERE event_type='coverage_batch_accepted'"
        ).fetchone()
    assert SessionEvent.model_validate(surviving).model_dump(mode="json") == rows(
        native_worker
    )[0]["body"]["accepted_event"]


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
def test_reader_refuses_corrupt_witness_and_changed_native_budget(native_worker, monkeypatch):
    env = native_worker
    original = coverage_store.mint_execution_receipt
    checked = 0

    class RollbackProbe(Exception):
        pass

    def probe(*args, **kwargs):
        nonlocal checked
        original(*args, **kwargs)
        connection, deployment, binding, event = args[:4]
        if checked:
            return
        checked += 1
        row = connection.execute(
            "SELECT body FROM coverage_execution_receipts WHERE event_id=%s", (event.event_id,),
        ).fetchone()
        for field in ("count", "generation", "binding", "deadline", "predecessor", "digest"):
            body = deepcopy(row["body"])
            if field == "count":
                body["accepted_count"] += 1
            elif field == "generation":
                body["command"]["pending"]["current_generation"] = False
            elif field == "binding":
                body["binding"]["namespace"] = "another-tenant"
            elif field == "deadline":
                body["valid_until"] = (binding.snapshot.expires_at + timedelta(days=1)).isoformat()
            elif field == "predecessor":
                body["predecessor_digest"] = "0" * 64
            digest = "0" * 64 if field == "digest" else coverage_digest(body)
            with pytest.raises(RollbackProbe), connection.transaction():
                # Controlled admin fault injection in this fixture's unique schema only.
                connection.execute("SET LOCAL session_replication_role=replica")
                connection.execute(
                    """UPDATE coverage_execution_receipts SET body=%s,body_digest=%s
                       WHERE event_id=%s""",
                    (Jsonb(body), digest, event.event_id),
                )
                with pytest.raises(ValueError):
                    read_execution_receipt(connection, deployment, binding)
                raise RollbackProbe
        for sql, match in (
            ("DELETE FROM coverage_model_calls", "model source/witness/budget changed"),
            ("DELETE FROM coverage_model_events", "model source/witness/budget changed"),
            ("DELETE FROM zebra_schema_migrations WHERE version=85", "prerequisite failed"),
        ):
            with pytest.raises(RollbackProbe), connection.transaction():
                connection.execute(sql)
                with pytest.raises(ValueError, match=match):
                    read_execution_receipt(connection, deployment, binding)
                raise RollbackProbe
        object_calls = list(env.client.calls)
        assert read_execution_receipt(connection, deployment, binding) is not None
        assert env.client.calls == object_calls

        class ExpiredAfterScan:
            scanned = False

            def execute(self, sql, params=None):
                if "native_fingerprint" in sql or "FROM coverage_model_revisions" in sql:
                    self.scanned = True
                if sql == "SELECT clock_timestamp() AS now":
                    assert self.scanned  # Deadline must be checked after the expensive read.
                    return SimpleNamespace(fetchone=lambda: {
                        "now": binding.snapshot.expires_at + timedelta(days=1),
                    })
                return connection.execute(sql, params)

        with pytest.raises(ValueError, match="deadline expired"):
            read_execution_receipt(ExpiredAfterScan(), deployment, binding)

    monkeypatch.setattr(coverage_store, "mint_execution_receipt", probe)
    run(env)
    assert checked == 1 and len(rows(env)) == 2
