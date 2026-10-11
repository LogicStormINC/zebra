"""Actual native Worker approval/pickup; synthetic Host/model/object transports."""
# ruff: noqa: F811

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from agent_core.domain.sessions import SessionStatus
from agent_storage.postgres.command_wakeup_handoff import HandoffStatus, handoff_command
from agent_storage.postgres.coverage import PostgresCoverageStore
from agent_storage.postgres.coverage_execution_receipts import (
    VerifiedCommitFacts,
    mint_execution_receipt,
)
from zebra_agent_config.coverage_settings import CoverageWorkSettings
from zebra_agent_worker.coverage_artifacts import CloudCoverageArtifacts
from zebra_agent_worker.coverage_continuation import (
    NATIVE_CONTINUATION_VERIFIER,
    continuation_has_budget,
)

from tests.worker.coverage_model_cloud_fixtures import NAMESPACE, dsn, postgres_dsn  # noqa: F401
from tests.worker.test_coverage_dispatch import native_handoff, native_worker  # noqa: F401
from tests.worker.test_coverage_multipart import model_cloud, part_count  # noqa: F401


def handoff_state(env):
    from psycopg import sql

    with env.database.connect() as connection:
        return tuple(connection.execute(sql.SQL(
            "SELECT to_jsonb(t) AS row FROM {} t ORDER BY to_jsonb(t)::text"
        ).format(sql.Identifier(table))).fetchall() for table in (
            "worker_leases", "session_command_pending", "command_handoff_receipts",
            "broker_command_inbox", "broker_outbox", "session_events",
        ))


def test_native_facade_qualifies_callback_identity_not_name_or_wrapper():
    from agent_integrations.coverage_model_derivation import derive_semantic_observation

    artifacts = object.__new__(CloudCoverageArtifacts)
    assert artifacts._execution_receipt_verifier(
        derive_semantic_observation
    ) == NATIVE_CONTINUATION_VERIFIER

    def wrapper(*args):
        return derive_semantic_observation(*args)

    assert artifacts._execution_receipt_verifier(wrapper) is None
    class Substitute(CloudCoverageArtifacts):
        pass
    assert object.__new__(Substitute)._execution_receipt_verifier(
        derive_semantic_observation
    ) is None


def test_opt_in_marker_without_verified_producer_never_mints_or_queries():
    class NoQueries:
        def execute(self, *args):
            pytest.fail("unqualified producer must not query or mint a qualified receipt")

    facts = VerifiedCommitFacts(None, 2, "a" * 64, False)
    mint_execution_receipt(
        NoQueries(), "fixture", None, None, facts, valid_until=None,
        verifier_contract=NATIVE_CONTINUATION_VERIFIER,
    )


@pytest.mark.parametrize("remaining,calls,tokens,allowed", [
    (True, 2, 0, False), (True, 1, 95, False), (True, 1, 90, True),
    (False, 2, 100, True), (None, 1, 0, False),
])
def test_remaining_budget_predicate(remaining, calls, tokens, allowed):
    facts = SimpleNamespace(
        model_work_remaining=remaining,
        budget=SimpleNamespace(calls=calls, charged_tokens=tokens),
    )
    policy = SimpleNamespace(max_calls=2, max_tokens=100)
    assert continuation_has_budget(facts, policy, SimpleNamespace(context_window=10)) is allowed


@pytest.fixture
def normal_worker(native_worker, monkeypatch):
    env = native_worker
    env.reply_from_request = True
    env.service._settings = replace(
        env.service._settings,
        coverage_work=CoverageWorkSettings(max_units=1, max_milliseconds=60000),
    )
    initialize = PostgresCoverageStore.__init__

    def composed(store, *args, **kwargs):
        initialize(store, *args, **(kwargs | {
            "execution_receipts": True, "execution_receipt_verifier": NATIVE_CONTINUATION_VERIFIER,
        }))

    monkeypatch.setattr(PostgresCoverageStore, "__init__", composed)
    return env


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
@pytest.mark.parametrize("part_count", [1, 3])
def test_normal_approval_and_pickup_skip_historical_object_reconstruction(
    normal_worker, monkeypatch,
):
    import zebra_agent_worker.coverage_recovery as recovery

    env = normal_worker

    def no_reconstruction(*args, **kwargs):
        pytest.fail("normal receipt must not construct a full model recovery transcript")

    monkeypatch.setattr(recovery, "_ModelVerification", no_reconstruction)
    first = native_handoff(env)
    assert first.status is HandoffStatus.ACCEPTED
    result = env.service.execute_claimed_session(first.lease, lease_ttl_seconds=300)
    assert result.session.status is SessionStatus.RUNNING
    with env.database.connect() as connection:
        approved = connection.execute(
            "SELECT * FROM command_recovery_attempts WHERE accepted_event_id=%s",
            (env.native_event.event_id,),
        ).fetchone()
        pending = connection.execute(
            "SELECT current_generation FROM session_command_pending WHERE accepted_event_id=%s",
            (env.native_event.event_id,),
        ).fetchone()
        receipt_count = connection.execute(
            "SELECT count(*) AS count FROM coverage_execution_receipts WHERE session_id=%s",
            (env.session,),
        ).fetchone()["count"]
    assert approved["reason"] == "coverage_continuation"
    assert approved["coverage_proof"]["continuation_protocol"] == "coverage-execution-receipt/1"
    assert approved["coverage_proof"]["accepted_count"] == 1
    assert approved["wake_generation"] == pending["current_generation"] == receipt_count == 1
    # Another qualified process cannot lend its extension to an unqualified v3 consumer.
    from uuid import uuid4

    from agent_storage.postgres.worker_capability import (
        PostgresWorkerCapabilities,
        WorkerCapabilityLostError,
    )
    from zebra_agent_worker.command_process_state import strict_worker_configuration_digest

    capabilities = PostgresWorkerCapabilities(env.dsn, deployment_namespace=NAMESPACE)
    legacy = capabilities.register(uuid4(), configuration_digest=strict_worker_configuration_digest(
        env.dsn, NAMESPACE, env.service._settings, env.service.execute_claimed_session,
        env.native_checker,
    ))
    objects_before_refusal = list(env.client.calls)
    state_before_refusal = handoff_state(env)
    with pytest.raises(WorkerCapabilityLostError):
        handoff_command(
            env.dsn, deployment_namespace=NAMESPACE, scope=env.scope,
            accepted_event_id=env.native_event.event_id, owner_instance_id="unqualified-v3",
            ttl=timedelta(minutes=5), coverage_check=env.native_checker,
            consumer_capability=legacy,
        )
    capabilities.revoke(legacy)
    assert env.client.calls == objects_before_refusal
    assert handoff_state(env) == state_before_refusal
    # Runtime clients without the new method cannot silently use legacy recovery.
    with pytest.raises(ValueError, match="supported native continuation consumer"):
        handoff_command(
            env.dsn, deployment_namespace=NAMESPACE, scope=env.scope,
            accepted_event_id=env.native_event.event_id, owner_instance_id="legacy-consumer",
            ttl=timedelta(minutes=5), coverage_check=lambda *args: {},
            consumer_capability=env.native_capability.lease_for(env.native_consumer),
        )
    assert handoff_state(env) == state_before_refusal
    assert env.client.calls == objects_before_refusal
    previous = first
    for _ in range(approved["coverage_proof"]["expected_count"]):
        if result.session.status is SessionStatus.COMPLETED:
            break
        objects = list(env.client.calls)
        second = native_handoff(env)
        assert second.status is HandoffStatus.ACCEPTED
        assert second.lease.fence != previous.lease.fence
        assert env.client.calls == objects  # Includes final locked revalidation.
        result = env.service.execute_claimed_session(second.lease, lease_ttl_seconds=300)
        previous = second
    assert result.session.status is SessionStatus.COMPLETED


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
@pytest.mark.parametrize("part_count", [1])
@pytest.mark.parametrize("change", ["revoke", "epoch"])
def test_authority_change_after_normal_preparation_has_no_partial_pickup(
    normal_worker, monkeypatch, change,
):
    from agent_storage import rotate_control_plane_epoch
    from agent_storage.postgres import command_wakeup_handoff as module
    from agent_storage.postgres.worker_capability import (
        PostgresWorkerCapabilities,
        WorkerCapabilityLostError,
    )

    env = normal_worker
    first = native_handoff(env)
    env.service.execute_claimed_session(first.lease, lease_ttl_seconds=300)
    before = handoff_state(env)
    objects = list(env.client.calls)
    prepare = module.prepare_command_handoff
    consumer_lease = env.native_capability.lease_for(env.native_consumer)
    injected = []

    def changed(*args, **kwargs):
        prepared = prepare(*args, **kwargs)
        assert prepared.proof["continuation_protocol"] == "coverage-execution-receipt/1"
        if change == "revoke":
            PostgresWorkerCapabilities(env.dsn, deployment_namespace=NAMESPACE).revoke(
                consumer_lease,
            )
        else:
            rotate_control_plane_epoch(env.dsn, deployment_namespace=NAMESPACE)
        injected.append(change)
        return prepared

    monkeypatch.setattr(module, "prepare_command_handoff", changed)
    with pytest.raises(WorkerCapabilityLostError):
        handoff_command(
            env.dsn, deployment_namespace=NAMESPACE, scope=env.scope,
            accepted_event_id=env.native_event.event_id, owner_instance_id="native-race",
            ttl=timedelta(minutes=5), coverage_check=env.native_checker,
            consumer_capability=consumer_lease,
        )
    assert injected == [change]
    assert handoff_state(env) == before
    assert env.client.calls == objects


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
@pytest.mark.parametrize("part_count", [1])
def test_normal_pickup_retains_current_host_revocation(normal_worker):
    env = normal_worker
    first = native_handoff(env)
    env.service.execute_claimed_session(first.lease, lease_ttl_seconds=300)
    objects = list(env.client.calls)
    env.wire.revoked = True
    refused = native_handoff(env)
    assert refused.status is HandoffStatus.REQUIRES_RECONCILIATION
    assert refused.lease is None
    assert env.client.calls == objects


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
@pytest.mark.parametrize("part_count", [1])
@pytest.mark.parametrize("change", ["stop", "approval"])
def test_marked_preparation_change_refuses_without_partial_pickup(
    normal_worker, monkeypatch, change,
):
    from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_storage.postgres import command_wakeup_handoff as module

    env = normal_worker
    first = native_handoff(env)
    env.service.execute_claimed_session(first.lease, lease_ttl_seconds=300)
    consumer = env.native_capability.lease_for(env.native_consumer)
    prepare = module.prepare_command_handoff
    injected = []
    objects = list(env.client.calls)

    def changed(*args, **kwargs):
        prepared = prepare(*args, **kwargs)
        assert prepared.proof["continuation_protocol"] == "coverage-execution-receipt/1"
        if change == "stop":
            events = env.service._event_store
            previous = events.list_for_session(env.session)[-1]
            command = SessionCommand(
                session_id=env.session, kind=SessionCommandKind.STOP,
                expected_revision=previous.sequence, idempotency_key="normal-pickup-stop",
            )
            events.append(SessionEvent.create(
                session_id=env.session, sequence=previous.sequence + 1,
                event_type=EventType.SESSION_COMMAND_ACCEPTED, actor=EventActor.USER,
                payload=command.event_payload(), idempotency_key=command.idempotency_key,
            ))
        else:
            with env.database.connect() as connection:
                connection.execute(
                    "UPDATE command_recovery_attempts SET coverage_proof="
                    "jsonb_set(coverage_proof,'{accepted_count}','0'::jsonb) "
                    "WHERE accepted_event_id=%s", (env.native_event.event_id,),
                )
        injected.append(handoff_state(env))
        return prepared

    monkeypatch.setattr(module, "prepare_command_handoff", changed)
    refused = handoff_command(
        env.dsn, deployment_namespace=NAMESPACE, scope=env.scope,
        accepted_event_id=env.native_event.event_id, owner_instance_id="native-change",
        ttl=timedelta(minutes=5), coverage_check=env.native_checker, consumer_capability=consumer,
    )
    assert refused.status is HandoffStatus.REQUIRES_RECONCILIATION and refused.lease is None
    assert len(injected) == 1 and handoff_state(env) == injected[0]
    assert env.client.calls == objects


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
@pytest.mark.parametrize("part_count", [1])
def test_marked_pickup_crash_after_native_writes_rolls_back_and_retries(
    normal_worker, monkeypatch,
):
    from agent_storage.postgres import command_wakeup_handoff as module

    from tests.worker.test_coverage_multipart import semantic_calls

    env = normal_worker
    first = native_handoff(env)
    env.service.execute_claimed_session(first.lease, lease_ttl_seconds=300)
    consumer = env.native_capability.lease_for(env.native_consumer)
    before = handoff_state(env)
    objects = list(env.client.calls)
    inbox = module._inbox
    crashed = []

    def interrupted(connection, namespace, pending, outbox, status):
        inbox(connection, namespace, pending, outbox, status)
        row = connection.execute(
            "SELECT fencing_token,wake_generation FROM command_handoff_receipts "
            "WHERE accepted_event_id=%s", (env.native_event.event_id,),
        ).fetchone()
        assert status == "accepted" and row["wake_generation"] == 1
        assert row["fencing_token"] > first.lease.fence.fencing_token
        crashed.append(row)
        raise RuntimeError("native pickup interrupted before commit")

    with monkeypatch.context() as patch:
        patch.setattr(module, "_inbox", interrupted)
        with pytest.raises(RuntimeError, match="interrupted before commit"):
            handoff_command(
                env.dsn, deployment_namespace=NAMESPACE, scope=env.scope,
                accepted_event_id=env.native_event.event_id, owner_instance_id="native-crash",
                ttl=timedelta(minutes=5), coverage_check=env.native_checker,
                consumer_capability=consumer,
            )
    assert len(crashed) == 1 and handoff_state(env) == before
    assert env.client.calls == objects
    assert semantic_calls(env) == 1
    retried = native_handoff(env)
    assert retried.status is HandoffStatus.ACCEPTED
    assert env.client.calls == objects
    after_retry = handoff_state(env)
    duplicate = handoff_command(
        env.dsn, deployment_namespace=NAMESPACE, scope=env.scope,
        accepted_event_id=env.native_event.event_id, owner_instance_id="duplicate-delivery",
        ttl=timedelta(minutes=5), coverage_check=env.native_checker,
        consumer_capability=env.native_capability.lease_for(env.native_consumer),
    )
    assert duplicate.status is HandoffStatus.DUPLICATE and duplicate.lease is None
    assert handoff_state(env) == after_retry and env.client.calls == objects
    from agent_storage.postgres.coverage_publication import CoveragePublicationQueries

    publication_checks = []
    verify_publication = CoveragePublicationQueries._verify_publication_lifecycle

    def verified_publication(store, *args, **kwargs):
        before_reads = len(env.client.calls)
        result = verify_publication(store, *args, **kwargs)
        publication_checks.append(len(env.client.calls) - before_reads)
        return result

    monkeypatch.setattr(
        CoveragePublicationQueries, "_verify_publication_lifecycle", verified_publication
    )
    with env.database.connect() as connection:
        expected_count = connection.execute(
            "SELECT coverage_proof->>'expected_count' AS count FROM command_recovery_attempts "
            "WHERE accepted_event_id=%s ORDER BY wake_generation DESC LIMIT 1",
            (env.native_event.event_id,),
        ).fetchone()["count"]
    for _ in range(int(expected_count)):
        result = env.service.execute_claimed_session(retried.lease, lease_ttl_seconds=300)
        if result.session.status is SessionStatus.COMPLETED:
            break
        retried = native_handoff(env)
        assert retried.status is HandoffStatus.ACCEPTED
    assert result.session.status is SessionStatus.COMPLETED
    assert semantic_calls(env) == 1
    assert publication_checks and all(reads > 0 for reads in publication_checks)
    with env.database.connect() as connection:
        assert connection.execute(
            "SELECT count(*) AS count FROM session_events WHERE session_id=%s "
            "AND event_type='coverage_report_certified'", (env.session,),
        ).fetchone()["count"] == 1


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
@pytest.mark.parametrize("part_count", [1])
def test_arbitrary_callback_cannot_qualify_native_prefix_by_opt_in(normal_worker, monkeypatch):
    from agent_integrations.coverage_model_derivation import derive_semantic_observation

    initialize = PostgresCoverageStore.__init__
    def composed(store, *args, **kwargs):
        initialize(store, *args, **kwargs)
        store._model_observation_deriver = lambda *args: derive_semantic_observation(*args)

    monkeypatch.setattr(PostgresCoverageStore, "__init__", composed)
    env = normal_worker
    first = native_handoff(env)
    result = env.service.execute_claimed_session(first.lease, lease_ttl_seconds=300)
    assert result.session.status is SessionStatus.RUNNING
    with env.database.connect() as connection:
        assert connection.execute(
            "SELECT count(*) AS count FROM coverage_execution_receipts WHERE session_id=%s",
            (env.session,),
        ).fetchone()["count"] == 0
        proof = connection.execute(
            "SELECT coverage_proof FROM command_recovery_attempts WHERE accepted_event_id=%s",
            (env.native_event.event_id,),
        ).fetchone()["coverage_proof"]
    assert "continuation_protocol" not in proof


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
@pytest.mark.parametrize("part_count", [1])
def test_exceptional_preparation_keeps_full_recovery_even_with_native_receipt(normal_worker):
    env = normal_worker
    first = native_handoff(env)
    env.service.execute_claimed_session(first.lease, lease_ttl_seconds=300)
    objects = list(env.client.calls)
    prepared = env.native_checker.prepare(NAMESPACE, env.native_event.event_id)
    assert "continuation_protocol" not in prepared.proof
    assert len(env.client.calls) > len(objects)
