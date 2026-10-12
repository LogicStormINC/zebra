"""Native PostgreSQL settlement exit/replay; model/S3 transport are controlled."""
# ruff: noqa: F811

from contextlib import contextmanager
from hashlib import sha256

import psycopg
import pytest
from agent_core.domain.artifact_objects import ArtifactObjectIntegrityError
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_core.domain.coverage_model_budget import CoverageModelUsageReceipt
from agent_core.domain.coverage_model_checkpoint import MODEL_CHECKPOINT_KIND
from agent_core.domain.leases import LeaseLostError
from agent_storage.postgres.work_unit import borrow_work_unit, postgres_work_unit

from tests.agent_integrations.test_coverage_model_invocation import invoke
from tests.worker.coverage_model_cloud_fixtures import (  # noqa: F401
    NAMESPACE,
    compose,
    dsn,
    model_cloud,
    postgres_dsn,
)
from tests.worker.test_coverage_model_cloud import database_state, private_artifact


def receipt(env):
    return CoverageModelUsageReceipt.model_validate(database_state(env)[1][0][1])


@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}],
                         indirect=True)
def test_native_settlement_returns_only_after_commit_and_rechecks_replay(model_cloud):
    env = model_cloud
    invocation = compose(env)
    first = invoke(env, invocation)
    _, body = private_artifact(env, MODEL_CHECKPOINT_KIND)
    before = database_state(env)
    sequence, verified = env.store.settle_model_checkpoint(
        env.binding, receipt(env), fence=env.fence,
    )
    assert type(sequence) is int and sequence == before[1][0][3] and verified == body
    assert borrow_work_unit((env.dsn, NAMESPACE)) is None
    assert database_state(env) == before
    assert invoke(env, compose(env)) == first and len(env.requests) == 1


@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}],
                         indirect=True)
@pytest.mark.parametrize("failure", ["bytes", "retention", "replacement"])
def test_native_settlement_never_delivers_old_proof_after_current_change(model_cloud, failure):
    env = model_cloud
    invoke(env, compose(env))
    identifier, _ = private_artifact(env, MODEL_CHECKPOINT_KIND)
    current = receipt(env)
    fence = env.fence
    if failure == "bytes":
        record = env.cloud._record(identifier)
        for value in env.client.objects.values():
            if sha256(value["Body"]).hexdigest() == record.reservation.sha256:
                value["Body"] = b"corrupt"
    elif failure == "retention":
        with env.database.connect() as connection:
            connection.execute("UPDATE artifact_payload_metadata SET request_created_at="
                               "request_created_at-interval '1 day',retained_until="
                               "clock_timestamp()-interval '1 second' WHERE artifact_id=%s",
                               (identifier,))
    else:
        env.leases.release(env.session, fence=fence)
    with pytest.raises((ValueError, CoverageRefusedError, LeaseLostError,
                        ArtifactObjectIntegrityError)):
        env.store.settle_model_checkpoint(env.binding, current, fence=fence)
    assert borrow_work_unit((env.dsn, NAMESPACE)) is None and len(env.requests) == 1


@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}],
                         indirect=True)
def test_verified_result_cannot_escape_an_uncommitted_owner(model_cloud):
    env = model_cloud
    invoke(env, compose(env))
    current = receipt(env)
    with postgres_work_unit(env.database):
        with pytest.raises(ValueError, match="own completed transaction"):
            env.store.settle_model_checkpoint(env.binding, current, fence=env.fence)
        assert env.store.record_model_usage(env.binding, current, fence=env.fence) > 0


@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}],
                         indirect=True)
def test_custom_acknowledgement_never_inherits_native_delivery(model_cloud, monkeypatch):
    env = model_cloud
    invoke(env, compose(env))
    current = receipt(env)
    before = database_state(env)
    original = env.store.record_model_usage
    for acknowledgement in (None, True, 0):
        with monkeypatch.context() as patch:
            patch.setattr(env.store, "record_model_usage",
                          lambda *a, result=acknowledgement, **k: result)
            with pytest.raises(ValueError, match="positive sequence"):
                env.store.settle_model_checkpoint(env.binding, current, fence=env.fence)
    calls = []

    def lost(*args, **kwargs):
        calls.append(original(*args, **kwargs))
        raise RuntimeError("ack lost after commit")

    with monkeypatch.context() as patch:
        patch.setattr(env.store, "record_model_usage", lost)
        with pytest.raises(RuntimeError, match="ack lost after commit"):
            env.store.settle_model_checkpoint(env.binding, current, fence=env.fence)
    assert len(calls) == 1 and database_state(env) == before and len(env.requests) == 1


@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}],
                         indirect=True)
@pytest.mark.parametrize("settled", [False, True])
@pytest.mark.parametrize("mutation", ["retention", "event"])
def test_scope_exit_mutation_rolls_back_first_settlement_and_replay(
    model_cloud, monkeypatch, settled, mutation,
):
    env = model_cloud
    invocation = compose(env)
    captured = []
    if settled:
        invoke(env, invocation)
        current = receipt(env)
    else:
        def stop(binding, usage, *, fence):
            captured.append(usage)
            raise RuntimeError("before settlement")

        with monkeypatch.context() as patch:
            patch.setattr(env.store, "record_model_usage", stop)
            with pytest.raises(CoverageRefusedError, match="unresolved_failure") as caught:
                invoke(env, invocation)
            assert isinstance(caught.value.__cause__, RuntimeError)
            assert str(caught.value.__cause__) == "before settlement"
        current = captured[0]
    before = database_state(env)
    identifier, _ = private_artifact(env, MODEL_CHECKPOINT_KIND)
    original = env.cloud._locked_proof_scope

    @contextmanager
    def changed(connection, *args, **kwargs):
        with original(connection, *args, **kwargs) as reader:
            yield reader
            if mutation == "retention":
                connection.execute("UPDATE artifact_payload_metadata SET request_created_at="
                                   "request_created_at-interval '1 day',retained_until="
                                   "clock_timestamp()-interval '1 second' WHERE artifact_id=%s",
                                   (identifier,))
            else:
                connection.execute("UPDATE session_events SET created_at=created_at+"
                                   "interval '1 second' WHERE event_id=(SELECT event_id FROM "
                                   "artifact_payload_metadata WHERE artifact_id=%s)",
                                   (identifier,))

    with monkeypatch.context() as patch:
        patch.setattr(env.cloud, "_locked_proof_scope", changed)
        with pytest.raises(
            (ValueError, psycopg.errors.ObjectNotInPrerequisiteState),
            match="canonical Event linkage|changed during settlement|"
                  "canonical Task Event business fields are immutable",
        ):
            env.store.settle_model_checkpoint(env.binding, current, fence=env.fence)
    assert database_state(env) == before
    assert borrow_work_unit((env.dsn, NAMESPACE)) is None
    assert env.store.settle_model_checkpoint(env.binding, current, fence=env.fence)[0] > 0
    assert len(env.requests) == 1
