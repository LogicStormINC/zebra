"""Real retention deadlines survive reads, callbacks and projection reconstruction."""

from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from agent_storage.postgres.coverage_model_source import replay_model
from agent_storage.postgres.coverage_transactions import lock_run

from tests.agent_storage.coverage_model_proof_fixtures import proof_env  # noqa: F401
from tests.agent_storage.test_coverage_model_checkpoint import (  # noqa: F401
    checkpoint_env,
    dsn,
    ledger,
    model_projections,
    postgres_dsn,
    publish_checkpoint,
    reserve,
    settle,
    spend,
)
from tests.agent_storage.test_coverage_publication import _certify, _read
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE


@pytest.fixture
def model_env(checkpoint_env):  # noqa: F811
    return checkpoint_env


def wait_past(env, deadline):
    # Real time/immutable original metadata, not a forged expiry or mocked clock.
    with psycopg.connect(env.dsn) as connection:
        connection.execute(
            "SELECT pg_sleep(greatest(0,extract(epoch FROM "
            "(%s::timestamptz-clock_timestamp())))+0.03)",
            (deadline,),
        )


def source_events(env):
    with psycopg.connect(env.dsn) as connection:
        return connection.execute(
            "SELECT to_jsonb(e) FROM session_events e WHERE deployment_namespace=%s "
            "AND session_id=%s ORDER BY sequence",
            (NAMESPACE, env.binding.session_id),
        ).fetchall()


@pytest.mark.parametrize("expired", [False, True])
@pytest.mark.parametrize("phase", ["reserve", "shared_rebuild", "certificate"])
def test_earliest_deadline_survives_delayed_second_original_read(
    model_env, proof_env, monkeypatch, phase, expired  # noqa: F811
):
    if phase == "certificate":
        env = proof_env(multipart=True, retention_seconds=45 if expired else 120)
        deadline = env.retention_deadline
        from uuid import UUID

        from agent_core.domain.identifiers import ArtifactId

        second_id = ArtifactId(UUID(env.receipts[1].checkpoint_ref.removeprefix("artifact://")))
        balance = (2, 60, 0)
    else:
        env = model_env(calls=3)
        first = reserve(env, key="first")
        second = first.model_copy(update={"reservation_key": "second"})
        spend(env, first)
        deadline = datetime.now(UTC) + timedelta(seconds=5 if expired else 60)
        settle(env, publish_checkpoint(env, first, retained_until=deadline))
        spend(env, second)
        settle(env, publish_checkpoint(env, second))
        second_id = env.checkpoint.artifact_id
        balance = (2, 20, 0)
    assert ledger(env) == balance
    read_method = (
        "read_payload_verified_bounded" if phase == "certificate"
        else "read_payload_bytes_bounded"
    )
    original = getattr(env.artifacts, read_method)
    delayed = False

    def read(ident, **kwargs):
        nonlocal delayed
        if ident == second_id and not delayed:
            delayed = True
            wait_past(env, deadline if expired else datetime.now(UTC))
        return original(ident, **kwargs)

    monkeypatch.setattr(env.artifacts, read_method, read)

    def invoke():
        if phase == "reserve":
            return spend(env, first.model_copy(update={"reservation_key": "third"}))
        if phase == "certificate":
            return _certify(env)
        with env.store._database.connect() as connection:
            lock_run(connection, NAMESPACE, env.binding, None)
            return replay_model(
                connection, NAMESPACE, env.binding, artifacts=env.artifacts, rebuild=True
            )

    before, events = model_projections(env), source_events(env)
    if expired:
        with pytest.raises((ValueError, RuntimeError), match="retention|expired|unavailable"):
            invoke()
        assert model_projections(env) == before and source_events(env) == events
        assert ledger(env) == balance
    else:
        result = invoke()
        if phase == "reserve":
            assert result.invoke and ledger(env) == (3, 90, 1)
    assert delayed


@pytest.mark.parametrize("late", [False, True])
@pytest.mark.parametrize("delay_at", ["authority", "final_validation"])
def test_first_certification_final_callback_obeys_original_model_deadline(
    proof_env, monkeypatch, late, delay_at  # noqa: F811
):
    # Native v2 derivation must finish lawfully before the deliberate final-boundary delay.
    env = proof_env(runtime=60)
    policy = env.store.model_budget_state(env.binding).policy
    checks = 0

    if delay_at == "final_validation":
        import agent_storage.postgres.coverage_publication as publication

        original = publication.validate_write
        validations = 0
        delayed = False

        def validate(*args, **kwargs):
            nonlocal validations, delayed
            result = original(*args, **kwargs)
            validations += 1
            issued = args[0].execute(
                "SELECT 1 FROM session_events WHERE deployment_namespace=%s AND session_id=%s "
                "AND event_type='coverage_report_certified' AND payload->>'namespace'=%s "
                "AND payload->>'run_id'=%s LIMIT 1",
                (NAMESPACE, env.binding.session_id, env.binding.namespace, env.binding.run_id),
            ).fetchone()
            if issued is not None and not delayed:
                delayed = True
                wait_past(env, policy.deadline if late else datetime.now(UTC))
            return result  # Deliberately stale clock from otherwise valid authority checks.

        monkeypatch.setattr(publication, "validate_write", validate)

    def authority():
        nonlocal checks
        checks += 1
        if checks == 3 and delay_at == "authority":
            wait_past(env, policy.deadline if late else datetime.now(UTC))

    before, events = model_projections(env), source_events(env)
    if late:
        with pytest.raises(ValueError, match="original MODEL deadline"):
            _certify(env, check_authority=authority)
        assert model_projections(env) == before and source_events(env) == events
        assert ledger(env) == (1, 30, 0)
        assert _read(env) is None
    else:
        certificate = _certify(env, check_authority=authority)
        assert certificate.created_at < policy.deadline
        wait_past(env, policy.deadline)
        after, issued = model_projections(env), source_events(env)
        # A committed original issuance still replays/reads after execution ends.
        assert _certify(env) == certificate
        assert _read(env)[0] == certificate
        assert model_projections(env) == after and source_events(env) == issued
    assert checks == 3
    if delay_at == "final_validation":
        assert delayed and validations >= 2


@pytest.mark.parametrize("expired", [False, True])
@pytest.mark.parametrize(
    "phase",
    [
        "reserve",
        "same_key",
        "settlement",
        "receipt_replay",
        "initialize",
        "rebuild",
        "deleted_rebuild",
        "shared_rebuild",
        "certificate_issue",
        "certificate_replay",
        "certificate_read",
        "certificate_rebuild",
    ],
)
def test_final_boundary_rechecks_verified_original_deadline(
    model_env, proof_env, monkeypatch, phase, expired  # noqa: F811
):
    if phase.startswith("certificate"):
        env = proof_env(retention_seconds=45 if expired else 120)
        deadline = env.retention_deadline
        balance = (1, 30, 0)
        if phase != "certificate_issue":
            _certify(env)
    else:
        env = model_env(calls=3)
        request = reserve(env)
        spend(env, request)
        deadline = datetime.now(UTC) + timedelta(seconds=5 if expired else 60)
        receipt = publish_checkpoint(env, request, retained_until=deadline)
        if phase != "settlement":
            settle(env, receipt)
        balance = (1, 10, 0)
    if phase == "deleted_rebuild":
        with psycopg.connect(env.dsn) as connection:
            for table in (
                "coverage_model_calls",
                "coverage_model_ledger",
                "coverage_model_events",
                "coverage_runs",
            ):
                connection.execute(f"DELETE FROM {table} WHERE run_id=%s", (env.binding.run_id,))
    delayed = False

    def delay():
        nonlocal delayed
        delayed = True
        wait_past(env, deadline if expired else datetime.now(UTC))

    if phase in {"reserve", "same_key", "settlement", "receipt_replay", "initialize"}:
        original = env.store._model_clock
        clocks = 0

        def clock(*args, **kwargs):
            nonlocal clocks
            original(*args, **kwargs)
            clocks += 1
            if clocks == (1 if phase == "initialize" else 2):
                delay()

        monkeypatch.setattr(env.store, "_model_clock", clock)
    elif phase in {"rebuild", "deleted_rebuild", "certificate_rebuild"}:
        original = env.store._rebuild_budget

        def rebuild(*args, **kwargs):
            original(*args, **kwargs)
            delay()

        monkeypatch.setattr(env.store, "_rebuild_budget", rebuild)
    elif phase == "shared_rebuild":
        import agent_storage.postgres.coverage_model_source as source

        original = source.witness_event

        def witness(*args, **kwargs):
            original(*args, **kwargs)
            if not delayed:
                delay()

        monkeypatch.setattr(source, "witness_event", witness)
    callbacks = 0

    def authority():
        nonlocal callbacks
        callbacks += 1
        if callbacks == 3:
            delay()

    def invoke():
        if phase == "reserve":
            return spend(env, request.model_copy(update={"reservation_key": "next"}))
        if phase == "same_key":
            return spend(env, request)
        if phase in {"settlement", "receipt_replay"}:
            return settle(env, receipt)
        if phase == "initialize":
            return env.store.initialize_model_budget(env.binding, fence=env.fence)
        if phase == "certificate_read":
            return _read(env, check_authority=authority)
        if phase in {"certificate_issue", "certificate_replay"}:
            return _certify(env, check_authority=authority)
        if phase == "shared_rebuild":
            with env.store._database.connect() as connection:
                lock_run(connection, NAMESPACE, env.binding, None)
                return replay_model(
                    connection, NAMESPACE, env.binding, artifacts=env.artifacts, rebuild=True
                )
        return env.store.rebuild(env.binding.namespace, env.binding.run_id)

    before, events = model_projections(env), source_events(env)
    if expired:
        with pytest.raises(ValueError, match="retention expired|Artifact is unavailable"):
            invoke()
        assert model_projections(env) == before and source_events(env) == events
        if phase == "settlement":
            assert ledger(env) == (1, 70, 1)
        elif phase == "deleted_rebuild":
            assert ledger(env) is None
        else:
            assert ledger(env) == balance
    else:
        assert invoke() is not None
    assert delayed
