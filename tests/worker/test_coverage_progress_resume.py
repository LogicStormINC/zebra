"""Coverage completion uses the durable attempt, including certificate recovery."""

from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.turns import InteractionMode
from agent_core.harness.models import HarnessAttemptOutcome
from zebra_agent_worker.coverage_certified import finish_certified_execution

from tests.worker.test_recorder_append_guards import _recorder


@pytest.mark.parametrize("attempt", [None, 1, 2, 7])
@pytest.mark.parametrize("recovered_tail", [False, True])
def test_certified_completion_closes_the_actual_durable_attempt(
    tmp_path, monkeypatch, attempt, recovered_tail,
):
    stores, recorder, session_id = _recorder(tmp_path)
    # Repeated starts need not be a contiguous count of attempts.
    if attempt is not None:
        recorder.append(EventType.HARNESS_ATTEMPT_STARTED, EventActor.HARNESS,
                        {"attempt_number": attempt})
        latest = recorder.prepare(EventType.HARNESS_ATTEMPT_STARTED, EventActor.HARNESS,
                                  {"attempt_number": attempt})
        if recovered_tail:
            stores.events.append(latest)
        else:
            recorder.append_event(latest)
        # Coverage's unit-budget counter must not replace the Harness Attempt.
        unit = SessionEvent.create(
            session_id=session_id, sequence=latest.sequence + 1,
            event_type=EventType.COVERAGE_UNIT_ATTEMPTED, actor=EventActor.SYSTEM,
            payload={"attempt_number": 99},
        )
        stores.events.append(unit)
    service = SimpleNamespace(
        _memory_extraction_service=None, _memory_promotion_service=None,
        _event_store=stores.events, _cloud_memory_store=Mock(),
        _projection_store=stores.sessions, _workspace_store=stores.workspaces,
        _task_index_store=stores.tasks,
    )
    certificate = Mock()
    certificate.model_dump.return_value = {"proof": "already-certified"}
    side_effects = Mock(side_effect=AssertionError("completion must defer cloud memory"))
    monkeypatch.setattr("zebra_agent_worker.execution_finalization.finalize_cloud_memory",
                        side_effects)
    expected = (pytest.raises(ValueError, match="requires a durable Attempt")
                if attempt is None else nullcontext())
    with expected:
        result = finish_certified_execution(
            service, SimpleNamespace(deployment_namespace="coverage-resume"), recorder,
            SimpleNamespace(session_id=session_id), certificate, "artifact://certified-report",
            Mock(), datetime.now(UTC), InteractionMode.ONE_SHOT,
        )
    events = stores.events.list_for_session(session_id)
    closes = [e for e in events if e.event_type in {
        EventType.TURN_COMPLETED, EventType.SESSION_COMPLETED,
    }]
    if attempt is None:
        assert not closes
        return
    assert len(closes) == 2
    assert all(e.payload["attempt_number"] == attempt for e in closes)
    assert result.attempt_result.outcome is HarnessAttemptOutcome.COMPLETED
    assert result.attempt_result.metadata == {
        "coverage_report_ref": "artifact://certified-report",
        "coverage_certificate": {"proof": "already-certified"},
    }
    side_effects.assert_not_called()


@pytest.mark.parametrize("starts", [(1,), (7,), (7, 7)])
def test_dispatch_uses_durable_harness_attempt_before_the_existing_bootstrap_gate(
    tmp_path, monkeypatch, starts,
):
    from agent_integrations import ModelProviderSettings
    from agent_integrations.openai_compatible import OpenAICompatibleModelGateway
    from zebra_agent_worker import coverage_dispatch as dispatch

    from tests.worker.test_coverage_bootstrap import inputs

    env = inputs()
    stores, recorder, session_id = _recorder(tmp_path)
    for number in starts:
        recorder.append(EventType.HARNESS_ATTEMPT_STARTED, EventActor.HARNESS,
                        {"attempt_number": number})
    recorder.append_event(SessionEvent.create(
        session_id=session_id, sequence=recorder.next_sequence,
        event_type=EventType.COVERAGE_UNIT_ATTEMPTED, actor=EventActor.SYSTEM,
        payload={"attempt_number": 99},
    ))
    connection = MagicMock()
    connection.execute.return_value.fetchall.side_effect = [[{}], [], []]
    connection.execute.return_value.fetchone.return_value = {"active_segment_id": session_id}
    runtime = SimpleNamespace(
        metadata=MagicMock(), deployment_namespace="coverage-resume", dsn="unused", objects=Mock(),
    )
    runtime.metadata._database.connect.return_value.__enter__.return_value = connection
    gateway = Mock()
    monkeypatch.setattr(dispatch.PostgresCoverageAuthority, "prepare", lambda *args: None)
    monkeypatch.setattr(dispatch, "postgres_work_unit", lambda _: nullcontext())
    monkeypatch.setattr(dispatch, "assert_current_lease_fence", Mock())
    monkeypatch.setattr(dispatch, "resolve_pinned_gateway", lambda *args: gateway)
    monkeypatch.setattr(dispatch, "frozen_or_discovered_manifest", lambda *args: Mock())
    monkeypatch.setattr(dispatch, "CloudCoverageEffectInvoke", Mock())
    monkeypatch.setattr(dispatch, "HostCoverageSnapshotSource", Mock())
    admission = env.admission.model_copy(update={"model_profile": dispatch.REVIEWER_PROFILE})
    monkeypatch.setattr(dispatch, "validate_coverage_admission", lambda *args, **kwargs: admission)
    monkeypatch.setattr(dispatch, "model_provider_settings", lambda _: ModelProviderSettings(
        provider="mock", api_key_env="UNUSED", base_url="https://model.invalid", model="fixture",
    ))
    model = object.__new__(OpenAICompatibleModelGateway)
    model._api_key = "fixture-only"
    monkeypatch.setattr(dispatch, "build_model_gateway", lambda _: model)
    monkeypatch.setattr(dispatch, "load_official_model_policy", Mock())
    bootstrap = Mock(side_effect=CoverageRefusedError(CoverageRefusalReason.UNSUPPORTED))
    monkeypatch.setattr(dispatch, "bootstrap_cloud_coverage", bootstrap)
    service = SimpleNamespace(
        _task_binding_loader=lambda _: env.task_binding,
        _cloud_artifact_factory=Mock(), _cloud_memory_store=Mock(), _effect_dispatch=Mock(),
        _settings=SimpleNamespace(host_tool_shared_secret="fixture-only"),
        _egress_registry=None, _frozen_manifest_loader=None,
    )
    execution_inputs = SimpleNamespace(
        task=SimpleNamespace(coverage_admission=admission, host_context=env.host,
                             policy_profile="read_only", network_profile="none"),
        claimed=SimpleNamespace(lease=SimpleNamespace(session_id=session_id, fence=Mock())),
        provider_continuation=None, recovered_handoff=None,
        session_events=[*env.bootstrap.events, *stores.events.read_since(session_id, 2)],
    )
    with pytest.raises(CoverageRefusedError):
        dispatch.execute_cloud_coverage(runtime, service, execution_inputs, recorder, lambda: None)
    bootstrap.assert_called_once()
    assert recorder.workspace.last_attempt_number == starts[-1] + 1
    assert recorder.events[-1].event_type is EventType.HARNESS_ATTEMPT_STARTED
    assert recorder.events[-1].payload["attempt_number"] == starts[-1] + 1
    assert not any(e.event_type is EventType.TURN_COMPLETED for e in recorder.events)
