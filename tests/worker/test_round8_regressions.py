"""Round-8 review regressions: runtime ownership, title cooldown, races."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.events import EventActor, EventType
from agent_storage import sqlite_control_plane_stores
from zebra_agent_worker.execution_errors import is_sequence_race
from zebra_agent_worker.execution_events import ExecutionInterrupted

NOW = datetime(2026, 8, 25, 14, 0, tzinfo=UTC)


def test_idempotency_conflict_is_not_a_sequence_race() -> None:
    from agent_storage import SessionEventIdempotencyConflictError

    conflict = SessionEventIdempotencyConflictError("same key, different content")
    assert not is_sequence_race(conflict)
    assert is_sequence_race(ValueError("duplicate or conflicting session event"))
    assert not is_sequence_race(ValueError("illegal transition"))
    assert not is_sequence_race(RuntimeError("boom"))


def test_title_recovery_cooldown_bounds_model_retries(tmp_path: Path) -> None:
    """generate() returning None must not re-bill the model every poll."""
    from zebra_agent_worker.cloud_memory_recovery import (
        TITLE_RETRY_COOLDOWN,
        CloudMemoryFinalizationRecovery,
    )

    calls = {"count": 0}

    class _TitleService:
        def generate(self, **kwargs):
            calls["count"] += 1
            return None

    stores = sqlite_control_plane_stores(tmp_path / "cooldown.sqlite")
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Cooldown",
            user_input="hold the line",
            workspace_root=tmp_path,
        )
    )
    for event in bootstrap.events:
        stores.events.append(event)
    # one terminal close so memory recovery finalizes and title is missing
    stores.events.append(
        __import__("agent_core.domain.events", fromlist=["SessionEvent"]).SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=bootstrap.session.current_sequence + 1,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
        )
    )
    events = stores.events.list_for_session(bootstrap.session.session_id)
    stores.events.append(
        __import__("agent_core.domain.events", fromlist=["SessionEvent"]).SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=events[-1].sequence + 1,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1, "summary": "done"},
        )
    )
    from agent_core.application.session_projection import rebuild_session
    from agent_core.application.workspace_projection import rebuild_workspace

    events = stores.events.list_for_session(bootstrap.session.session_id)
    stores.sessions.save_session(rebuild_session(events))
    stores.workspaces.save_workspace(rebuild_workspace(events))

    class _NoMemoryStore:
        def get_worker_commit_receipt(self, *args, **kwargs):
            # A present receipt short-circuits the memory branch so the
            # recovery reaches the title logic without needing a cloud
            # mutation authority in this unit test.
            return SimpleNamespace(receipt=SimpleNamespace(session_revision=0))

        def list_for_worker(self, *args, **kwargs):
            return []

    class _Claims:
        def claim_session(self, session_id, **kwargs):
            return SimpleNamespace(
                lease=SimpleNamespace(fence=None, session_id=session_id),
                recovery=SimpleNamespace(
                    session=stores.sessions.get_session(session_id),
                    workspace=stores.workspaces.get_workspace(session_id),
                ),
            )

        def release_claim(self, claimed):
            return None

        def release_lease(self, lease):
            return None

        def heartbeat(self, lease, **kwargs):
            return None

    class _Factory:
        @staticmethod
        def build(*, session, workspace, lease, ownership_check):
            from uuid import uuid4

            from agent_core.domain.leases import LeaseFence
            from agent_core.ports.aggregate_mutation import (
                WorkerMutationAuthority,
            )
            from zebra_agent_worker.execution_events import (
                DurableHarnessEventRecorder,
            )
            from zebra_agent_worker.model_call_index import ModelCallIndexer
            from zebra_agent_worker.tool_run_index import ToolRunIndexer

            authority = WorkerMutationAuthority(
                deployment_namespace="cooldown-test",
                session_id=session.session_id,
                lease_fence=LeaseFence(
                    control_plane_epoch=uuid4(),
                    fencing_token=1,
                    owner_instance_id="w",
                ),
                expected_stream_revision=session.current_sequence,
            )
            return DurableHarnessEventRecorder(
                session=session,
                workspace=workspace,
                event_store=stores.events,
                projection_store=stores.sessions,
                workspace_store=stores.workspaces,
                model_call_indexer=ModelCallIndexer(stores.model_calls),
                tool_run_indexer=ToolRunIndexer(stores.tool_runs),
                worker_projection_transaction=SimpleNamespace(),
                worker_mutation_authority=authority,
            )

    service = CloudMemoryFinalizationRecovery(
        claim_service=_Claims(),
        recorder_factory=_Factory(),
        memory_store=_NoMemoryStore(),
        deployment_namespace="cooldown-test",
        event_store=stores.events,
        projection_store=stores.sessions,
        workspace_store=stores.workspaces,
        title_service_factory=lambda: _TitleService(),
    )

    first = service.recover(
        bootstrap.session.session_id,
        worker_id="w",
        recovered_at=NOW,
        lease_ttl_seconds=30,
    )
    second = service.recover(
        bootstrap.session.session_id,
        worker_id="w",
        recovered_at=NOW + timedelta(seconds=1),
        lease_ttl_seconds=30,
    )

    assert first is True and second is True
    assert calls["count"] == 1  # the cooldown suppressed the second poll
    # after the cooldown expires a retry is allowed again
    third = service.recover(
        bootstrap.session.session_id,
        worker_id="w",
        recovered_at=NOW + TITLE_RETRY_COOLDOWN + timedelta(seconds=1),
        lease_ttl_seconds=30,
    )
    assert third is True
    assert calls["count"] == 2


def test_gateway_failure_after_setup_closes_the_gateway(tmp_path: Path) -> None:
    """A control interruption after gateway creation must not leak it."""
    import zebra_agent_worker.runtime_authority as runtime_authority

    closed = {"count": 0}
    original_close = runtime_authority.close_tool_gateway

    def counting_close(gateway):
        closed["count"] += 1
        return original_close(gateway)

    import sys

    from agent_core.application.mock_model import (
        ScriptedModelGateway,
        ScriptedModelResponse,
    )
    from agent_core.domain.identifiers import new_message_id
    from agent_core.domain.messages import MessageRole, SessionMessage
    from agent_core.domain.modeling import ModelCompletion

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api" / "http_app"))
    from fastapi.testclient import TestClient
    from http_app_support import _settings
    from zebra_agent_api import create_http_app

    def gateway_factory(_settings):
        return ScriptedModelGateway(
            responses=(
                ScriptedModelResponse(
                    completion=ModelCompletion(
                        assistant_message=SessionMessage(
                            message_id=new_message_id(),
                            role=MessageRole.ASSISTANT,
                            content="unused",
                            created_at=NOW,
                        )
                    )
                ),
            )
        )

    database_path = tmp_path / "ownership.sqlite"
    client = TestClient(create_http_app(database_path, settings=_settings(None)))
    created = client.post(
        "/tasks",
        json={"prompt": "Own the runtime.", "title": "Ownership"},
    )
    task_id = created.json()["task_id"]

    import zebra_agent_worker.execution_continuations as continuations_module

    original_start = continuations_module.recover_and_start_continuations

    def interrupted_start(*args, **kwargs):
        raise ExecutionInterrupted("concurrent cancellation won")

    import zebra_agent_worker.execution as ex

    original_gateway_attr = ex.build_model_gateway
    ex.build_model_gateway = gateway_factory
    continuations_module.recover_and_start_continuations = interrupted_start
    runtime_authority.close_tool_gateway = counting_close
    try:
        response = client.post(f"/tasks/{task_id}/resume", json={})
    finally:
        ex.build_model_gateway = original_gateway_attr
        continuations_module.recover_and_start_continuations = original_start
        runtime_authority.close_tool_gateway = original_close

    assert response.status_code == 200, response.text
    # No real cancel event exists in this fixture, so the superseded result
    # reports the durable projection status (ready) — the load-bearing
    # assertion is that the boundary RELEASED the gateway instead of
    # leaking it past the interrupted continuation start.
    assert closed["count"] >= 1
