"""Native source-retention guards, including a stale repeatable-read writer.

These raw rows test storage constraints, not qualification of a fast-path proof.
"""
# ruff: noqa: F811

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.coverage_contracts import coverage_digest
from agent_core.domain.coverage_model_budget import CoverageModelReservation
from agent_core.domain.coverage_validation import expected_units
from agent_core.domain.events import EventType
from agent_storage.postgres import migration_runner
from agent_storage.postgres.coverage_model_source import replay_model, task_policy, witness_event
from agent_storage.postgres.coverage_transactions import append_coverage_event
from psycopg.types.json import Jsonb

from tests.agent_storage.test_coverage_model_budget import model_env  # noqa: F401
from tests.agent_storage.test_coverage_model_checkpoint import publish_checkpoint
from tests.worker.coverage_model_cloud_fixtures import (  # noqa: F401
    NAMESPACE,
    dsn,
    model_cloud,
    postgres_dsn,
)


@pytest.fixture(autouse=True)
def schema_version(request, monkeypatch):
    migrations = migration_runner.MIGRATIONS
    if getattr(request, "param", 85) == 84:
        monkeypatch.setattr(
            migration_runner,
            "MIGRATIONS",
            tuple(m for m in migrations if m.version <= 84),
        )

    def upgrade(dsn, *, through=85):
        # This test proves the specific84-to85 retention upgrade, not later fleet DDL.
        monkeypatch.setattr(
            migration_runner,
            "MIGRATIONS",
            tuple(m for m in migrations if through is None or m.version <= through),
        )
        migration_runner.apply_postgres_migrations(dsn)

    return upgrade


@pytest.fixture
def legacy_model(model_env, monkeypatch):
    from agent_storage.postgres import coverage

    native_seed = coverage.seed_run

    # ponytail: adapt only today's added seed column to the actual v84 table;
    # never add future DDL or relax an old migration's storage guards.
    class LegacyCursor:
        def __init__(self, cursor):
            self.cursor = cursor

        def __enter__(self):
            self.cursor.__enter__()
            return self

        def __exit__(self, *args):
            return self.cursor.__exit__(*args)

        def executemany(self, statement, rows):
            assert "unit_key,record)" in statement
            return self.cursor.executemany(
                statement.replace("unit_key,record)", "unit_key)").replace(
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)", "VALUES (%s,%s,%s,%s,%s,%s)"
                ),
                (row[:-1] for row in rows),
            )

    class LegacySeed:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def cursor(self):
            return LegacyCursor(self.connection.cursor())

    monkeypatch.setattr(
        coverage,
        "seed_run",
        lambda connection, *args: native_seed(
            LegacySeed(connection),
            *args,
        ),
    )
    old = model_env()
    database = old.store._database

    def append(connection, kind, body):
        sequence = (
            connection.execute(
                "SELECT current_version FROM session_streams WHERE deployment_namespace=%s "
                "AND session_id=%s",
                (NAMESPACE, old.binding.session_id),
            ).fetchone()["current_version"]
            + 1
        )
        event = append_coverage_event(
            connection,
            NAMESPACE,
            old.binding,
            old.fence,
            sequence,
            kind,
            body,
        )
        witness_event(connection, NAMESPACE, old.binding, event)
        return event

    # Bootstrap era-appropriate ledger rows rather than invoke today's indexed
    # MODEL helpers, which require later native summary/source functions.
    with database.connect() as connection:
        policy = task_policy(connection, NAMESPACE, old.binding)
        append(
            connection,
            EventType.COVERAGE_MODEL_BUDGET_INITIALIZED,
            {"policy": policy.model_dump(mode="json")},
        )
        reservation = CoverageModelReservation(
            reservation_key="legacy-call",
            admission_digest=policy.admission_digest,
            key=expected_units(old.binding.contract, old.items)[0],
            request_digest="b" * 64,
            model_profile=policy.model_profile,
            token_bound=70,
        )
        reserved = append(
            connection,
            EventType.COVERAGE_MODEL_CALL_RESERVED,
            {"reservation": reservation.model_dump(mode="json")},
        )
        connection.execute(
            "INSERT INTO coverage_model_ledger VALUES (%s,%s,%s,%s,1,70,1)",
            (
                NAMESPACE,
                old.binding.namespace,
                old.binding.run_id,
                Jsonb(policy.model_dump(mode="json")),
            ),
        )
        connection.execute(
            "INSERT INTO coverage_model_calls VALUES (%s,%s,%s,%s,%s,%s,NULL,NULL)",
            (
                NAMESPACE,
                old.binding.namespace,
                old.binding.run_id,
                reservation.reservation_key,
                Jsonb(reservation.model_dump(mode="json")),
                reserved.sequence,
            ),
        )
    receipt = publish_checkpoint(old, reservation)
    with database.connect() as connection:
        usage = append(
            connection,
            EventType.COVERAGE_MODEL_USAGE_RECORDED,
            {"receipt": receipt.model_dump(mode="json")},
        )
        connection.execute(
            "UPDATE coverage_model_calls SET receipt=%s,receipt_sequence=%s",
            (Jsonb(receipt.model_dump(mode="json")), usage.sequence),
        )
        connection.execute("UPDATE coverage_model_ledger SET charged_tokens=10,unresolved=0")
    return SimpleNamespace(
        dsn=old.dsn,
        database=database,
        binding=old.binding,
        session=old.binding.session_id,
        cloud=old.cloud,
    )


def source(connection, env, *, kind="coverage_batch_accepted"):
    event = uuid4()
    connection.execute(
        """INSERT INTO session_events
           (deployment_namespace,event_id,session_id,sequence,event_type,payload,actor,created_at)
           SELECT %s,%s,%s,coalesce(max(sequence),-1)+1,%s,%s,'harness',clock_timestamp()
           FROM session_events WHERE deployment_namespace=%s AND session_id=%s""",
        (
            NAMESPACE,
            event,
            env.session,
            kind,
            Jsonb({"namespace": NAMESPACE, "run_id": env.binding.run_id}),
            NAMESPACE,
            env.session,
        ),
    )
    connection.execute(
        """UPDATE session_streams SET current_version=(SELECT sequence FROM session_events
           WHERE deployment_namespace=%s AND event_id=%s)
           WHERE deployment_namespace=%s AND session_id=%s""",
        (NAMESPACE, event, NAMESPACE, env.session),
    )
    return event


def seal(connection, env, event, **overrides):
    body = {"protocol": "coverage-execution-receipt/1"}
    connection.execute(
        """INSERT INTO coverage_execution_receipts
           (deployment_namespace,namespace,run_id,session_id,event_id,sequence,body,body_digest)
           SELECT deployment_namespace,%s,%s,%s,event_id,coalesce(%s,sequence),%s,%s
           FROM session_events WHERE deployment_namespace=%s AND event_id=%s""",
        (
            overrides.get("namespace", NAMESPACE),
            overrides.get("run_id", env.binding.run_id),
            overrides.get("session_id", env.session),
            overrides.get("sequence"),
            Jsonb(body),
            coverage_digest(body),
            NAMESPACE,
            event,
        ),
    )


def test_source_seal_retains_only_receipt_sources_and_rolls_back(model_cloud):
    env = model_cloud
    with env.database.connect() as connection:
        event = source(connection, env)
        unassigned = SimpleNamespace(session=uuid4(), binding=env.binding)
        connection.execute(
            "INSERT INTO session_streams VALUES (%s,%s,0)", (NAMESPACE, unassigned.session)
        )
        other = source(connection, unassigned)
    with pytest.raises(ValueError, match="abort seal"):
        with env.database.connect() as connection:
            seal(connection, env, event)
            raise ValueError("abort seal")
    with env.database.connect() as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM coverage_execution_receipts WHERE event_id=%s",
                (event,),
            ).fetchone()
            is None
        )
        seal(connection, env, event)
    for statement in (
        "UPDATE session_events SET created_at=created_at+interval '1 microsecond' "
        "WHERE event_id=%s",
        "UPDATE session_events SET created_at=created_at WHERE event_id=%s",
        "DELETE FROM session_events WHERE event_id=%s",
    ):
        with pytest.raises(psycopg.errors.RaiseException, match="sources are sealed"):
            with env.database.connect() as connection:
                connection.execute(statement, (event,))
    with pytest.raises(psycopg.errors.RaiseException, match="sources are sealed"):
        with env.database.connect() as connection:
            connection.execute("TRUNCATE session_events CASCADE")
    with env.database.connect() as connection:
        # No receipt and no Task allocation: the independent source guards do
        # not mistake an unrelated unassigned source for a retained receipt.
        connection.execute(
            "UPDATE session_events SET created_at=created_at+interval '1 microsecond' "
            "WHERE event_id=%s",
            (other,),
        )
        connection.execute("DELETE FROM session_events WHERE event_id=%s", (other,))


def test_stale_repeatable_read_writer_cannot_miss_committed_receipt(model_cloud):
    env = model_cloud
    with env.database.connect() as connection:
        event = source(connection, env)
    with pytest.raises(psycopg.errors.SerializationFailure):
        with env.database.connect() as stale:
            stale.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            stale.execute("SELECT 1 FROM session_events WHERE event_id=%s", (event,))
            with env.database.connect() as writer:
                seal(writer, env, event)
            stale.execute("UPDATE session_events SET actor='stale' WHERE event_id=%s", (event,))


def test_concurrent_source_writer_waits_for_seal_then_refuses(model_cloud):
    env = model_cloud
    with env.database.connect() as connection:
        event = source(connection, env)
    started = Event()

    def mutate():
        with env.database.connect() as writer:
            writer.execute("SET LOCAL statement_timeout='5s'")
            started.set()
            writer.execute("UPDATE session_events SET actor='racing' WHERE event_id=%s", (event,))

    with ThreadPoolExecutor(max_workers=1) as pool:
        with env.database.connect() as writer:
            seal(writer, env, event)
            future = pool.submit(mutate)
            assert started.wait(2)
            with pytest.raises(TimeoutError):
                future.result(timeout=0.1)
        with pytest.raises(psycopg.errors.RaiseException, match="sources are sealed"):
            future.result(timeout=5)


def test_receipt_cannot_seal_non_acceptance_event(model_cloud):
    env = model_cloud
    with env.database.connect() as connection:
        event = source(connection, env, kind="other")
    with pytest.raises(psycopg.errors.RaiseException, match="requires native accepted source"):
        with env.database.connect() as connection:
            seal(connection, env, event)


@pytest.mark.parametrize("field", ["namespace", "run_id", "session_id", "sequence"])
def test_receipt_source_scope_mismatch_refuses(model_cloud, field):
    env = model_cloud
    with env.database.connect() as connection:
        event = source(connection, env)
    value = uuid4() if field == "session_id" else 100000 if field == "sequence" else "different"
    with pytest.raises(psycopg.errors.RaiseException, match="requires native accepted source"):
        with env.database.connect() as connection:
            seal(connection, env, event, **{field: value})


@pytest.mark.parametrize("schema_version", [84], indirect=True)
@pytest.mark.parametrize("tampered", [False, True])
def test_upgrade_preserves_old_model_witness_and_seals_old_receipt(
    schema_version,
    legacy_model,
    tampered,
):
    env = legacy_model
    with env.database.connect() as connection:
        assert (
            connection.execute(
                "SELECT max(version) AS version FROM zebra_schema_migrations"
            ).fetchone()["version"]
            == 84
        )
        witness = connection.execute(
            "SELECT source_row FROM coverage_model_events ORDER BY sequence LIMIT 1"
        ).fetchone()["source_row"]
        if tampered:
            # Positioned Event originals are immutable even in v84. Corrupt the
            # independently stored legacy witness instead; the upgrade must not
            # repair it into fresh authority or reset the historical charge.
            connection.execute(
                "UPDATE coverage_model_events SET source_row=jsonb_set(source_row,'{actor}',"
                "'\"tool\"'::jsonb) WHERE source_row->>'event_id'=%s",
                (witness["event_id"],),
            )
            witness = connection.execute(
                "SELECT source_row FROM coverage_model_events ORDER BY sequence LIMIT 1"
            ).fetchone()["source_row"]
        event = source(connection, env)
        seal(connection, env, event)
    # Capture the committed original, after any queued Task-coordinate allocation.
    with env.database.connect() as connection:
        original_source = connection.execute(
            "SELECT to_jsonb(e) AS body FROM session_events e WHERE event_id=%s",
            (event,),
        ).fetchone()["body"]
    schema_version(env.dsn)
    with env.database.connect() as connection:
        assert (
            connection.execute(
                "SELECT max(version) AS version FROM zebra_schema_migrations"
            ).fetchone()["version"]
            == 85
        )
        assert (
            connection.execute(
                "SELECT to_jsonb(e) AS body FROM session_events e WHERE event_id=%s",
                (event,),
            ).fetchone()["body"]
            == original_source
        )
        assert (
            connection.execute(
                "SELECT source_row FROM coverage_model_events ORDER BY sequence LIMIT 1"
            ).fetchone()["source_row"]
            == witness
        )

    # v85 has no v96 SQL helper. Inline exactly its three derived-coordinate
    # exclusions while keeping every query/read on the real historical schema;
    # do not install unrelated later DDL just to call today's Python verifier.
    class HistoricalSourceReads:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, statement, args=None):
            for body in ("to_jsonb(e)", "w.source_row"):
                statement = statement.replace(
                    f"coverage_model_event_source({body})",
                    f"({body}-ARRAY['task_id','task_sequence','projection_block_start']::text[])",
                )
            return self.connection.execute(statement, args)

    with env.database.connect() as connection:
        historical = HistoricalSourceReads(connection)
        if tampered:
            with pytest.raises(ValueError, match="model source proof witness conflicts"):
                replay_model(historical, NAMESPACE, env.binding, artifacts=env.cloud)
        else:
            state, _ = replay_model(historical, NAMESPACE, env.binding, artifacts=env.cloud)
            assert state is not None and (state.calls, state.charged_tokens, state.unresolved) == (
                1,
                10,
                0,
            )
    with pytest.raises(psycopg.errors.RaiseException, match="sources are sealed"):
        with env.database.connect() as connection:
            connection.execute("DELETE FROM session_events WHERE event_id=%s", (event,))
