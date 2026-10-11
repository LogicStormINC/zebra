"""Native delta transcripts keep full budget integrity and independent replay."""
# ruff: noqa: F811

from hashlib import sha256

import pytest
from agent_core.domain.artifact_objects import ArtifactObjectIntegrityError
from agent_storage.postgres.coverage_model_acceptance import verify_model_results
from agent_storage.postgres.coverage_model_replay_rows import model_rows
from agent_storage.postgres.coverage_model_source import MODEL_TYPES
from agent_storage.postgres.coverage_model_verification import _ModelVerification
from agent_storage.postgres.coverage_transactions import lock_run

from tests.agent_storage.test_coverage_model_verification_native import two_records
from tests.worker.coverage_model_cloud_fixtures import (  # noqa: F401
    NAMESPACE,
    dsn,
    model_cloud,
    postgres_dsn,
)


@pytest.fixture
def env(model_cloud):
    return two_records(model_cloud)


@pytest.mark.parametrize(
    "model_cloud", [600, {"validation_mode": "final_certification"}],
    indirect=True, ids=["eager", "incremental"],
)
def test_delta_transcript_is_record_scoped_but_budget_remains_global(env):
    with env.store._database.connect() as connection:
        lock_run(connection, NAMESPACE, env.binding, env.fence)
        accepted = env.store._accepted_results(connection, env.binding)
        selected = tuple(item for item in accepted if item.key.record_id == "second_record")
        transcript = _ModelVerification(
            connection, NAMESPACE, env.binding, artifacts=env.cloud,
            derive=env.store._model_observation_deriver, _commit_results=selected,
        )
        assert transcript.state.calls == 2
        assert transcript.state.unresolved == 0
        incremental = transcript.policy.validation_mode == "final_certification"
        assert len(transcript.calls) == (1 if incremental else 2)
        assert len(list(model_rows(connection, NAMESPACE, env.binding, MODEL_TYPES))) == 5
        assert len(list(model_rows(
            connection, NAMESPACE, env.binding, MODEL_TYPES, record_ids=["second_record"],
        ))) == 3
        assert {value[1].reservation.key.record_id for value in transcript.settled.values()} == (
            {"second_record"} if incremental else {item.key.record_id for item in accepted}
        )
        transcript.verify(selected, deadlines=[])
        full = _ModelVerification(
            connection, NAMESPACE, env.binding, artifacts=env.cloud,
            derive=env.store._model_observation_deriver,
        )
        assert len(full.calls) == 2
        full.verify(accepted, deadlines=[])
        facts = []
        verify_model_results(
            connection, NAMESPACE, env.binding, selected, artifacts=env.cloud,
            derive=env.store._model_observation_deriver, deadlines=[],
            incremental_commit=True, verified_commits=facts,
        )
        if incremental:
            assert len(facts) == 1 and facts[0].model_work_remaining is False
        else:
            assert not facts


@pytest.mark.parametrize(
    "model_cloud", [{"validation_mode": "final_certification"}], indirect=True,
)
def test_delta_transcript_rejects_unrelated_native_index_corruption(env):
    with env.store._database.connect() as connection:
        lock_run(connection, NAMESPACE, env.binding, env.fence)
        accepted = env.store._accepted_results(connection, env.binding)
        selected = tuple(item for item in accepted if item.key.record_id == "second_record")
        connection.execute(
            """UPDATE coverage_model_calls SET reserved_sequence=0
               WHERE deployment_namespace=%s AND namespace=%s AND run_id=%s
                 AND reservation #>> '{key,record_id}'<>%s""",
            (NAMESPACE, env.binding.namespace, env.binding.run_id, "second_record"),
        )
        with pytest.raises(ValueError, match="conflict"):
            _ModelVerification(
                connection, NAMESPACE, env.binding, artifacts=env.cloud,
                derive=env.store._model_observation_deriver, _commit_results=selected,
            )
        connection.rollback()


@pytest.mark.parametrize(
    "model_cloud", [{"validation_mode": "final_certification"}], indirect=True,
)
def test_unrelated_object_loss_is_deferred_but_full_proof_refuses(env):
    with env.store._database.connect() as connection:
        lock_run(connection, NAMESPACE, env.binding, env.fence)
        accepted = env.store._accepted_results(connection, env.binding)
        selected = tuple(item for item in accepted if item.key.record_id == "second_record")
        receipt = connection.execute(
            """SELECT receipt FROM coverage_model_calls WHERE deployment_namespace=%s
               AND namespace=%s AND run_id=%s AND reservation #>> '{key,record_id}'<>%s""",
            (NAMESPACE, env.binding.namespace, env.binding.run_id, "second_record"),
        ).fetchone()["receipt"]
        original = next(value for value in env.client.objects.values()
                        if sha256(value["Body"]).hexdigest() == receipt["checkpoint_digest"])
        original["Body"] = b"corrupt"
        delta = _ModelVerification(
            connection, NAMESPACE, env.binding, artifacts=env.cloud,
            derive=env.store._model_observation_deriver, _commit_results=selected,
        )
        delta.verify(selected, deadlines=[])
        with pytest.raises(ArtifactObjectIntegrityError, match="read expectation"):
            _ModelVerification(
                connection, NAMESPACE, env.binding, artifacts=env.cloud,
                derive=env.store._model_observation_deriver,
            )
