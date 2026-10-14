from types import SimpleNamespace
from unittest.mock import Mock

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.stream_admission import StreamMode
from agent_core.harness.models import HarnessEventDraft
from zebra_agent_config import load_settings
from zebra_agent_worker import transient_output_composition as composition

from tests.agent_core.test_transient_output_contract import authorization, generation


def test_legacy_returns_existing_sink_and_unknown_mode_drops_drafts(monkeypatch):
    identity = generation()
    auth = authorization(identity)
    scope = SimpleNamespace(
        task_id=identity.task_id, run_id=identity.run_id, anchor_event_id="anchor"
    )
    progress = SimpleNamespace(head=SimpleNamespace(scope=scope, through_sequence=9))
    stores = SimpleNamespace(tasks=Mock(), leases=Mock())
    stores.tasks.read_run_header.return_value = SimpleNamespace(
        anchor=SimpleNamespace(event_id="anchor")
    )
    monkeypatch.setattr(composition, "StreamProofReader", Mock())
    factory = composition.compose_transient_output_factory(
        stores, dsn="postgresql://unused", namespace="ns", settings=load_settings({})
    )
    monkeypatch.setattr(composition, "load_run_stream_admission", lambda *args: None)
    assert factory(progress, SimpleNamespace(fence=auth.lease_fence)) is None
    monkeypatch.setattr(composition, "load_run_stream_admission", Mock(side_effect=TimeoutError()))
    sink = factory(progress, SimpleNamespace(fence=auth.lease_fence))
    saved = []
    output = sink.wrap(saved.append)
    sink.start_public_call("call-1", 1)
    for kind in (EventType.MODEL_RESPONSE_DELTA, EventType.MODEL_RESPONSE_RECEIVED):
        output(
            HarnessEventDraft(
                kind,
                EventActor.HARNESS,
                {"model_call_id": "call-1", "attempt_number": 1, "content_delta": "draft"},
            )
        )
    assert [event.event_type for event in saved] == [EventType.MODEL_RESPONSE_RECEIVED]


def test_v2_without_transport_does_not_fallback_when_admission_disabled(monkeypatch):
    identity = generation()
    auth = authorization(identity)
    scope = SimpleNamespace(
        task_id=identity.task_id, run_id=identity.run_id, anchor_event_id="anchor"
    )
    progress = SimpleNamespace(head=SimpleNamespace(scope=scope, through_sequence=9))
    stores = SimpleNamespace(tasks=Mock(), leases=Mock())
    monkeypatch.setattr(composition, "StreamProofReader", Mock())
    stores.tasks.read_run_header.return_value = SimpleNamespace(
        anchor=SimpleNamespace(event_id="anchor")
    )
    monkeypatch.setattr(
        composition,
        "load_run_stream_admission",
        lambda *args: SimpleNamespace(mode=StreamMode.TRANSIENT_V2),
    )
    sink = composition.compose_transient_output_factory(
        stores, dsn="postgresql://unused", namespace="ns", settings=load_settings({})
    )(progress, auth)
    assert sink is not None and sink._port is None
    # No actual request / Turn evidence: callback remains fail-closed even without Redis.
    sink.start_public_call("call-1", 1)
    saved = []
    sink.wrap(saved.append)(
        HarnessEventDraft(
            EventType.MODEL_RESPONSE_DELTA,
            EventActor.HARNESS,
            {"model_call_id": "call-1", "attempt_number": 1, "content_delta": "draft"},
        )
    )
    assert saved == []


def test_real_cloud_loop_wires_mode_factory_and_binding_without_memory(tmp_path, monkeypatch):
    from dataclasses import replace

    from zebra_agent_worker.cloud_composition import compose_cloud_worker
    from zebra_agent_worker.loop import build_worker_loop_service

    from tests.test_cloud_api_worker_profile_composition import _cloud_settings
    from tests.worker.test_command_recovery import _settings

    monkeypatch.setattr("agent_storage.runtime_composition.require_current_schema", lambda _: None)
    bundle = compose_cloud_worker(_cloud_settings())
    bundle = replace(bundle, stores=replace(bundle.stores, memories=None))
    monkeypatch.setattr(
        "zebra_agent_worker.command_process_state.command_cutover_state", lambda *a, **kw: False
    )
    captured = {}

    def execution(**kw):
        captured.update(kw)
        return Mock()

    monkeypatch.setattr("zebra_agent_worker.loop.SessionExecutionService", execution)
    service = build_worker_loop_service(
        database_path=tmp_path / "unused", settings=_settings(), cloud_worker_composition=bundle
    )
    assert callable(captured["transient_output_factory"])
    assert callable(captured["task_binding_loader"])
    assert service._command_consumer is not None
