from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread

from agent_core.application.mock_model import ScriptedModelGateway
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.model_calls import ModelCallRecord
from agent_core.domain.modeling import ModelCompletion, ModelTextDelta, ModelToolDefinition
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.tool_runs import ToolRunRecord
from agent_core.ports.runtime import EffectiveRuntimeAuthority, RuntimeClass
from agent_runtime import LocalRuntime
from agent_security import LocalPolicyEngine, NetworkProfile
from agent_storage import (
    SQLiteArtifactPayloadStore,
    SQLiteEventStore,
    SQLiteLeaseStore,
    SQLiteModelCallStore,
    SQLiteToolRunStore,
    SQLiteWorkspaceProjectionStore,
)
from agent_storage.artifact_projection import payload_for_artifact_uri
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings
from worker_execution_support import (
    _assistant_only_gateway,
    _build_execution_service,
    _created_at,
    _seed_ready_session,
    _seed_ready_session_with_input,
    _tool_gateway,
)
from zebra_agent_worker.claims import SessionClaimService
from zebra_agent_worker.control import SessionControlService


def test_worker_execution_service_completes_ready_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_ready_session(database_path, tmp_path)

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )

    result = _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-a",
        executed_at=_created_at(),
    )

    assert result.session.status is SessionStatus.COMPLETED
    assert result.attempt_result.metadata["assistant_message"] == "Worker completed the session."
    assert SQLiteLeaseStore(database_path).get(session_id) is None
    model_calls = SQLiteModelCallStore(database_path).list_for_session(session_id)
    assert len(model_calls) == 1
    assert isinstance(model_calls[0], ModelCallRecord)


def test_worker_execution_keeps_recovered_lease_during_long_model_call(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_ready_session(database_path, tmp_path)
    complete = ScriptedModelGateway.complete
    heartbeat_lease = SessionClaimService.heartbeat_lease
    background_heartbeat = Event()

    def slow_complete(self, messages, *, tools=()):
        assert background_heartbeat.wait(timeout=2)
        return complete(self, messages, tools=tools)

    def observed_heartbeat(self, lease, *, lease_ttl_seconds, checkpoint=None):
        if checkpoint is None:
            background_heartbeat.set()
        return heartbeat_lease(
            self,
            lease,
            lease_ttl_seconds=lease_ttl_seconds,
            checkpoint=checkpoint,
        )

    monkeypatch.setattr(ScriptedModelGateway, "complete", slow_complete)
    monkeypatch.setattr(SessionClaimService, "heartbeat_lease", observed_heartbeat)
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )

    result = _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-long-model",
        executed_at=_created_at(),
        lease_ttl_seconds=1,
    )

    assert result.session.status is SessionStatus.COMPLETED
    assert SQLiteLeaseStore(database_path).get(session_id) is None


def test_worker_persists_effective_runtime_authority_before_attempt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_ready_session(database_path, tmp_path)

    class AuthorityRuntime(LocalRuntime):
        def provision(self, *, workspace_root=None, spec=None):
            handle = super().provision(workspace_root=workspace_root, spec=spec)
            authorized = replace(
                handle,
                runtime_name="gvisor",
                authority=EffectiveRuntimeAuthority(
                    runtime_class=RuntimeClass.GVISOR,
                    engine="docker",
                    image="zebra/runtime@sha256:" + "a" * 64,
                    spec_digest="b" * 64,
                    network_enforcement="container-network-none",
                    workspace_writable=True,
                ),
            )
            self._handles[handle.handle_id] = authorized
            return authorized

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )
    monkeypatch.setattr(
        "zebra_agent_worker.runtime_setup.build_runtime",
        lambda *args, **kwargs: AuthorityRuntime(snapshot_root=tmp_path / "runtime"),
    )

    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-hard-runtime",
        executed_at=_created_at(),
    )

    events = SQLiteEventStore(database_path).list_for_session(session_id)
    authority_index = next(
        index
        for index, event in enumerate(events)
        if event.event_type is EventType.RUNTIME_PROVISIONED
    )
    attempt_index = next(
        index
        for index, event in enumerate(events)
        if event.event_type is EventType.HARNESS_ATTEMPT_STARTED
    )
    assert authority_index < attempt_index
    workspace = SQLiteWorkspaceProjectionStore(database_path).get_workspace(session_id)
    assert workspace is not None
    assert workspace.runtime_name == "gvisor"
    assert workspace.runtime_spec_digest == "b" * 64


def test_worker_execution_persists_model_text_deltas_before_final_response(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_ready_session(database_path, tmp_path)

    class StreamingGateway:
        def complete(
            self,
            messages: list[SessionMessage],
            *,
            tools: tuple[ModelToolDefinition, ...] = (),
        ) -> ModelCompletion:
            raise AssertionError("worker must use the streaming gateway path")

        def complete_stream(
            self,
            messages: list[SessionMessage],
            *,
            tools: tuple[ModelToolDefinition, ...] = (),
            on_text_delta: Callable[[ModelTextDelta], None],
        ) -> ModelCompletion:
            assert messages
            assert tools
            on_text_delta(ModelTextDelta(index=0, content="Stream "))
            on_text_delta(ModelTextDelta(index=1, content="complete."))
            return ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="Stream complete.",
                    created_at=_created_at(),
                )
            )

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: StreamingGateway(),
    )

    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-stream",
        executed_at=_created_at(),
    )

    events = SQLiteEventStore(database_path).list_for_session(session_id)
    execution_types = [event.event_type for event in events[3:]]
    assert execution_types[:5] == [
        EventType.HARNESS_ATTEMPT_STARTED,
        EventType.MODEL_REQUEST_STARTED,
        EventType.MODEL_RESPONSE_DELTA,
        EventType.MODEL_RESPONSE_DELTA,
        EventType.MODEL_RESPONSE_RECEIVED,
    ]
    deltas = [
        event.payload for event in events if event.event_type is EventType.MODEL_RESPONSE_DELTA
    ]
    assert [delta["content_delta"] for delta in deltas] == ["Stream ", "complete."]
    final = next(event for event in events if event.event_type is EventType.MODEL_RESPONSE_RECEIVED)
    assert final.payload["model_call_id"] == deltas[0]["model_call_id"]


def test_worker_streaming_stops_cleanly_after_durable_cancellation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_ready_session(database_path, tmp_path)
    first_delta = Event()
    release = Event()

    class BlockingStreamingGateway:
        def complete(
            self,
            messages: list[SessionMessage],
            *,
            tools: tuple[ModelToolDefinition, ...] = (),
        ) -> ModelCompletion:
            raise AssertionError("worker must use the streaming gateway path")

        def complete_stream(
            self,
            messages: list[SessionMessage],
            *,
            tools: tuple[ModelToolDefinition, ...] = (),
            on_text_delta: Callable[[ModelTextDelta], None],
        ) -> ModelCompletion:
            on_text_delta(ModelTextDelta(index=0, content="Started"))
            first_delta.set()
            assert release.wait(timeout=2)
            on_text_delta(ModelTextDelta(index=1, content=" too late"))
            raise AssertionError("cancelled stream must stop before final completion")

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: BlockingStreamingGateway(),
    )
    results = []

    def execute() -> None:
        results.append(
            _build_execution_service(database_path).execute_session(
                session_id,
                worker_id="worker-cancel",
                executed_at=_created_at(),
            )
        )

    thread = Thread(target=execute)
    thread.start()
    assert first_delta.wait(timeout=2)
    SessionControlService(database_path).cancel_session(session_id)
    release.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert results[0].session.status is SessionStatus.CANCELLED
    event_types = [
        event.event_type for event in SQLiteEventStore(database_path).list_for_session(session_id)
    ]
    assert event_types[-1] is EventType.SESSION_CANCELLED
    assert EventType.SESSION_FAILED not in event_types


def test_worker_execution_recovers_network_authority(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_ready_session_with_input(
        database_path,
        tmp_path,
        user_input="Continue with bounded network authority.",
        network_profile="domain-allowlist",
        network_allowlist=("docs.example.com",),
    )
    captured: list[NetworkProfile] = []

    def build_policy(*, profile, network_profile, web_search_endpoint, trusted_local):
        captured.append(network_profile)
        assert web_search_endpoint is None
        assert trusted_local is False
        return LocalPolicyEngine(profile=profile, network_profile=network_profile)

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )
    monkeypatch.setattr("zebra_agent_worker.execution.LocalPolicyEngine", build_policy)

    _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-network",
        executed_at=_created_at(),
    )

    assert captured[0].name.value == "domain-allowlist"
    assert captured[0].domain_allowlist == ("docs.example.com",)


def test_cloud_setup_only_is_persistently_rejected_before_model_start(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "worker.db"
    session_id = _seed_ready_session_with_input(
        database_path,
        tmp_path,
        user_input="Install the setup dependencies first.",
        network_profile="setup-only",
    )
    settings = ZebraAgentSettings(
        profile="cloud",
        database_url=str(database_path),
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
    )
    service = _build_execution_service(database_path)
    service._settings = settings
    service._artifact_payload_store = None
    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: (_ for _ in ()).throw(AssertionError("model must not start")),
    )

    result = service.execute_session(
        session_id,
        worker_id="worker-cloud-setup",
        executed_at=_created_at(),
    )

    assert result.session.status is SessionStatus.FAILED
    assert result.attempt_result.metadata["stop_reason"] == "unsupported_runtime_capability"
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    assert events[-1].event_type is EventType.SESSION_FAILED
    assert events[-1].payload["metadata"]["network_profile"] == "setup-only"


def test_worker_execution_service_indexes_tool_run(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "worker.db"
    (tmp_path / "README.md").write_text("worker readme\n", encoding="utf-8")
    session_id = _seed_ready_session(database_path, tmp_path)

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: _tool_gateway(settings=settings),
    )

    result = _build_execution_service(database_path).execute_session(
        session_id,
        worker_id="worker-a",
        executed_at=_created_at(),
    )

    tool_runs = SQLiteToolRunStore(database_path).list_for_session(session_id)
    assert result.session.status is SessionStatus.COMPLETED
    assert len(tool_runs) == 1
    assert isinstance(tool_runs[0], ToolRunRecord)
    assert tool_runs[0].tool_name == "files.read"
    assert tool_runs[0].status == "executed"
    assert tool_runs[0].artifact_uri is not None
    # CTX-ART-02: artifact_uri is now artifact://; resolve via payload store.
    stored_payload = payload_for_artifact_uri(
        SQLiteArtifactPayloadStore(database_path), tool_runs[0].artifact_uri
    )
    assert stored_payload is not None
    assert (
        Path(stored_payload.access_uri.removeprefix("file://")).read_text(encoding="utf-8")
        == "worker readme\n"
    )
