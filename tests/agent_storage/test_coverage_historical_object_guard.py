"""Incremental optimization must not silently weaken historical-object refusal."""

from hashlib import sha256

import pytest
from agent_core.domain.artifact_objects import (
    ArtifactObjectIntegrityError,
    ArtifactObjectNotFoundError,
)
from agent_core.domain.coverage_model_budget import CoverageModelUsageReceipt
from agent_core.domain.events import EventType
from agent_storage.postgres.coverage_projection import replay_request

from tests.agent_storage.test_coverage_model_verification_native import two_records
from tests.agent_storage.test_postgres_command_wakeup import dsn, postgres_dsn  # noqa: F401
from tests.worker.coverage_model_cloud_fixtures import model_cloud  # noqa: F401
from tests.worker.test_coverage_model_cloud import database_state


def damage_original(env, request, damage, *, selected=False):
    receipt = next(
        value
        for row in database_state(env)[1]
        for value in (CoverageModelUsageReceipt.model_validate(row[1]),)
        if (value.reservation.key.record_id == request.results[0].key.record_id) == selected
    )
    key = next(
        key
        for key, value in env.client.objects.items()
        if sha256(value["Body"]).hexdigest() == receipt.checkpoint_digest
    )
    if damage == "delete":
        del env.client.objects[key]
    else:
        env.client.objects[key]["Body"] = b"corrupted original"


@pytest.mark.parametrize("damage", ["delete", "corrupt"])
def test_unrelated_commit_retry_still_requires_original_history(model_cloud, damage):  # noqa: F811
    env = two_records(model_cloud)
    events = env.events.list_for_session(env.session)
    last = next(e for e in reversed(events) if e.event_type is EventType.COVERAGE_BATCH_ACCEPTED)
    request = replay_request(env.artifacts, env.binding, last)
    damage_original(env, request, damage)
    before = database_state(env)
    with pytest.raises((ArtifactObjectIntegrityError, ArtifactObjectNotFoundError)):
        env.store.commit(request, fence=env.fence)
    assert database_state(env) == before
    assert env.events.list_for_session(env.session) == events


@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
@pytest.mark.parametrize("damage", ["delete", "corrupt"])
def test_incremental_merge_still_requires_its_selected_original(model_cloud, damage):  # noqa: F811
    env = two_records(model_cloud)
    events = env.events.list_for_session(env.session)
    last = next(e for e in reversed(events) if e.event_type is EventType.COVERAGE_BATCH_ACCEPTED)
    request = replay_request(env.artifacts, env.binding, last)
    assert request.results[0].key.kind == "record_merge"
    damage_original(env, request, damage, selected=True)
    before = database_state(env)
    with pytest.raises((ArtifactObjectIntegrityError, ArtifactObjectNotFoundError)):
        env.store.commit(request, fence=env.fence)
    assert database_state(env) == before
    assert env.events.list_for_session(env.session) == events


@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
@pytest.mark.parametrize("damage", ["delete", "corrupt"])
def test_incremental_retry_defers_unrelated_damage_but_certification_refuses(
    model_cloud,  # noqa: F811
    damage,
):
    env = two_records(model_cloud)
    events = env.events.list_for_session(env.session)
    last = next(e for e in reversed(events) if e.event_type is EventType.COVERAGE_BATCH_ACCEPTED)
    request = replay_request(env.artifacts, env.binding, last)
    damage_original(env, request, damage)
    before = database_state(env)
    receipt = env.store.commit(request, fence=env.fence)
    assert receipt.event_watermark == last.sequence
    assert database_state(env) == before
    with pytest.raises((ArtifactObjectIntegrityError, ArtifactObjectNotFoundError)):
        env.store.certify(
            env.binding.namespace,
            env.binding.run_id,
            report_ref=env.report_artifact.uri,
            report_digest=env.report_artifact.sha256,
            fence=env.fence,
            check_authority=lambda: None,
        )
    assert env.events.list_for_session(env.session) == events
