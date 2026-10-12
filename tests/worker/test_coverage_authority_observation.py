"""Current authority observation never projects a borrowed uncommitted tail."""
# ruff: noqa: F401,F811

from dataclasses import replace
from inspect import currentframe

import pytest
from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_core.domain.sessions import SessionStatus
from agent_integrations.coverage_snapshot_source import HostCoverageSnapshotSource
from agent_storage.postgres.command_wakeup_handoff import HandoffStatus
from agent_storage.postgres.coverage_artifact_publication import PostgresCoverageArtifactPublisher
from zebra_agent_config.coverage_settings import CoverageWorkSettings
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.execution_finalization import WorkerExecutionError

from tests.worker.coverage_model_cloud_fixtures import dsn, model_cloud, postgres_dsn
from tests.worker.test_coverage_dispatch import native_handoff, native_worker


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
def test_private_publications_do_not_project_but_finalization_does(native_worker, monkeypatch):
    env = native_worker
    env.service._settings = replace(
        env.service._settings,
        coverage_work=CoverageWorkSettings(max_milliseconds=60000),
    )
    consumers = []
    recorder_state = None
    publication_lags = []
    project = DurableHarnessEventRecorder.project_persisted_tail
    publish = PostgresCoverageArtifactPublisher.publish_batch

    def traced(recorder):
        nonlocal recorder_state
        recorder_state = recorder
        frame = currentframe().f_back
        caller = frame.f_code.co_name
        consumers.append(caller)
        assert caller not in {"check_local_native", "authority"}, (
            "read/private evidence authority attempted user-facing projection writes"
        )
        return project(recorder)

    def publication(publisher, binding, payloads, **kwargs):
        with env.database.connect() as connection:
            version = connection.execute(
                "SELECT current_version FROM session_streams "
                "WHERE deployment_namespace=%s AND session_id=%s",
                (env.database.deployment_namespace, env.session),
            ).fetchone()["current_version"]
        assert kwargs["authority"].expected_stream_revision == version
        if recorder_state is not None:
            publication_lags.append(version - recorder_state.session.current_sequence)
        return publish(publisher, binding, payloads, **kwargs)

    monkeypatch.setattr(DurableHarnessEventRecorder, "project_persisted_tail", traced)
    monkeypatch.setattr(PostgresCoverageArtifactPublisher, "publish_batch", publication)
    handoff = native_handoff(env)
    assert handoff.status is HandoffStatus.ACCEPTED
    result = env.service.execute_claimed_session(handoff.lease, lease_ttl_seconds=300)
    assert result.session.status is SessionStatus.COMPLETED
    assert "finish_certified_execution" in consumers
    assert len(publication_lags) > 1 and max(publication_lags) > 0
    assert min(publication_lags) >= 0


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
def test_host_descriptor_exit_rechecks_current_local_authority(native_worker, monkeypatch):
    import zebra_agent_worker.coverage_dispatch as dispatch

    env = native_worker
    armed = checked = False
    descriptor = HostCoverageSnapshotSource._get_descriptor

    def revoke(source, *args, **kwargs):
        result = descriptor(source, *args, **kwargs)
        if armed:
            # A real SQL authority change during otherwise successful Host I/O.
            # No canonical descriptor or original evidence bytes are changed.
            with env.database.connect() as connection:
                connection.execute(
                    "UPDATE session_projections SET status='cancelled' "
                    "WHERE deployment_namespace=%s AND session_id=%s",
                    (env.database.deployment_namespace, env.session),
                )
        return result

    def compose_model(**kwargs):
        nonlocal armed, checked
        armed = True
        with pytest.raises(CoverageRefusedError) as refusal:
            kwargs["check_authority"]()
        assert refusal.value.reason is CoverageRefusalReason.AUTHORITY_INVALID
        checked = True
        # Stop at this tested boundary rather than continue a cancelled task.
        raise refusal.value

    monkeypatch.setattr(HostCoverageSnapshotSource, "_get_descriptor", revoke)
    monkeypatch.setattr(dispatch, "NativeSemanticCoverageModel", compose_model)
    handoff = native_handoff(env)
    assert handoff.status is HandoffStatus.ACCEPTED
    with pytest.raises(WorkerExecutionError, match="strict coverage refused: authority_invalid"):
        env.service.execute_claimed_session(handoff.lease, lease_ttl_seconds=300)
    assert checked
    assert not any(
        event.event_type.value == "coverage_report_certified"
        for event in env.events.list_for_session(env.session)
    )
