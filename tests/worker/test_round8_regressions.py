"""Round-8 review regressions: runtime ownership, title cooldown, races."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_storage import sqlite_control_plane_stores
from zebra_agent_worker.execution_errors import is_sequence_race
from zebra_agent_worker.execution_events import ExecutionInterrupted

NOW = datetime(2026, 8, 25, 14, 0, tzinfo=UTC)


def test_only_the_typed_sequence_conflict_is_a_race() -> None:
    from agent_storage import (
        SessionEventIdempotencyConflictError,
        SessionEventSequenceConflictError,
    )

    assert is_sequence_race(SessionEventSequenceConflictError("lost the cas"))
    conflict = SessionEventIdempotencyConflictError("same key, different content")
    assert not is_sequence_race(conflict)
    # The legacy text and every other integrity failure fail closed.
    assert not is_sequence_race(ValueError("duplicate or conflicting session event"))
    assert not is_sequence_race(ValueError("illegal transition"))
    assert not is_sequence_race(RuntimeError("boom"))


def test_title_recovery_cooldown_bounds_model_retries(tmp_path: Path) -> None:
    """generate() returning None must not re-bill the model every poll."""
    from zebra_agent_worker.cloud_memory_recovery import (
        TITLE_RETRY_COOLDOWN,
        CloudMemoryFinalizationRecovery,
    )

    calls = {"count": 0}
    first_at = NOW + TITLE_RETRY_COOLDOWN - timedelta(seconds=1)
    expected_bucket = {
        "value": int(first_at.timestamp() // TITLE_RETRY_COOLDOWN.total_seconds())
    }

    class _TitleService:
        def generate(self, **kwargs):
            assert (
                stores.idempotency.get(
                    action="worker-title-retry",
                    idempotency_key=(
                        "worker-title-retry:"
                        f"{bootstrap.session.session_id}:{expected_bucket['value']}"
                    ),
                )
                is not None
            )
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
        idempotency_store=stores.idempotency,
        deployment_namespace="cooldown-test",
        event_store=stores.events,
        projection_store=stores.sessions,
        workspace_store=stores.workspaces,
        title_service_factory=lambda: _TitleService(),
    )
    # A second Worker process shares ONLY the durable store.
    other_worker = CloudMemoryFinalizationRecovery(
        claim_service=_Claims(),
        recorder_factory=_Factory(),
        memory_store=_NoMemoryStore(),
        idempotency_store=stores.idempotency,
        deployment_namespace="cooldown-test",
        event_store=stores.events,
        projection_store=stores.sessions,
        workspace_store=stores.workspaces,
        title_service_factory=lambda: _TitleService(),
    )

    first = service.recover(
        bootstrap.session.session_id,
        worker_id="w",
        recovered_at=first_at,
        lease_ttl_seconds=30,
    )
    second = other_worker.recover(
        bootstrap.session.session_id,
        worker_id="w2",
        recovered_at=first_at + timedelta(seconds=1),
        lease_ttl_seconds=30,
    )

    assert first is True and second is True
    from zebra_agent_worker.cloud_memory_recovery import (
        MEMORY_RECOVERY_ACTION,
        memory_recovery_key,
    )

    completion_revision = events[-1].sequence
    assert (
        stores.idempotency.get(
            action=MEMORY_RECOVERY_ACTION,
            idempotency_key=memory_recovery_key(
                bootstrap.session.session_id,
                completion_revision,
            ),
        )
        is not None
    )
    # One second across a bucket boundary is still inside the rolling cooldown.
    assert calls["count"] == 1
    # After the rolling cooldown expires a retry is allowed again.
    third_at = first_at + TITLE_RETRY_COOLDOWN + timedelta(seconds=1)
    expected_bucket["value"] = int(
        third_at.timestamp() // TITLE_RETRY_COOLDOWN.total_seconds()
    )
    third = other_worker.recover(
        bootstrap.session.session_id,
        worker_id="w",
        recovered_at=third_at,
        lease_ttl_seconds=30,
    )
    assert third is True
    assert calls["count"] == 2


def test_title_reservation_loser_does_not_own_the_paid_attempt() -> None:
    from agent_core.domain.identifiers import new_session_id
    from agent_core.ports import IdempotencyRecord
    from zebra_agent_worker.cloud_memory_recovery import _reserve_title_attempt

    class _LostRaceStore:
        def get(self, **kwargs):
            return None

        def save(self, record):
            return IdempotencyRecord(
                action=record.action,
                idempotency_key=record.idempotency_key,
                request_hash=record.request_hash,
                status_code=record.status_code,
                response_body={
                    "attempted_at": record.created_at.isoformat(),
                    "reservation_id": "other-worker",
                },
                created_at=record.created_at,
            )

    assert not _reserve_title_attempt(_LostRaceStore(), new_session_id(), NOW)


def test_gateway_failure_after_setup_closes_the_gateway(tmp_path: Path) -> None:
    """A control interruption after gateway creation must not leak it."""
    import zebra_agent_worker.runtime_authority as runtime_authority

    closed = {"count": 0}
    original_close = runtime_authority.close_tool_gateway

    def counting_close(gateway):
        closed["count"] += 1
        original_close(gateway)
        return RuntimeError("simulated cleanup failure")

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
    assert closed["count"] == 1
    from uuid import UUID

    from agent_core.domain.identifiers import SessionId
    from agent_storage import SQLiteEventStore

    events = SQLiteEventStore(database_path).list_for_session(SessionId(UUID(task_id)))
    cleanup_events = [
        event for event in events if event.event_type is EventType.RUNTIME_CLEANUP_FAILED
    ]
    assert len(cleanup_events) == 1
    assert cleanup_events[0].payload == {
        "target": "tool_gateway",
        "error_type": "RuntimeError",
        "attempt_number": 1,
    }


def test_cloud_memory_scan_does_not_hide_deterministic_value_errors() -> None:
    import pytest
    from agent_core.domain.identifiers import new_session_id
    from agent_core.domain.sessions import SessionStatus
    from zebra_agent_worker.cloud_memory_recovery import recover_completed_cloud_memory

    class _Recovery:
        def recover(self, *args, **kwargs):
            raise ValueError("cloud Memory projection is misconfigured")

    projection = SimpleNamespace(
        list_recent_sessions=lambda **kwargs: [
            SimpleNamespace(session_id=new_session_id(), status=SessionStatus.COMPLETED)
        ]
    )
    with pytest.raises(ValueError, match="misconfigured"):
        recover_completed_cloud_memory(
            worker_id="worker-a",
            batch_size=1,
            lease_ttl_seconds=30,
            recovery=_Recovery(),
            projection_store=projection,
        )


def test_cloud_memory_scan_includes_old_durable_pending_sessions() -> None:
    from agent_core.domain.identifiers import new_session_id
    from agent_core.domain.sessions import SessionStatus
    from zebra_agent_worker.cloud_memory_recovery import recover_completed_cloud_memory

    old_session = SimpleNamespace(
        session_id=new_session_id(),
        status=SessionStatus.COMPLETED,
    )
    recent_session = SimpleNamespace(
        session_id=new_session_id(),
        status=SessionStatus.AWAITING_TURN,
    )
    recovered: list[object] = []

    class _Recovery:
        def recover(self, session_id, **kwargs):
            recovered.append(session_id)
            return True

    projection = SimpleNamespace(
        list_memory_recovery_sessions=lambda **kwargs: [old_session],
        list_recent_sessions=lambda **kwargs: [recent_session],
    )

    recover_completed_cloud_memory(
        worker_id="worker-a",
        batch_size=1,
        lease_ttl_seconds=30,
        recovery=_Recovery(),
        projection_store=projection,
    )

    assert recovered == [old_session.session_id, recent_session.session_id]


def _build_receipt_session(tmp_path: Path, *, with_follow_up: bool):
    """Real SQLite stores + real recorder; memory events REALLY occupy
    sequences 5-6 so the receipt carries session_revision=6."""
    from uuid import uuid4

    from agent_core.application.session_projection import rebuild_session
    from agent_core.application.workspace_projection import rebuild_workspace
    from agent_core.domain.identifiers import MemoryId
    from agent_core.domain.leases import LeaseFence
    from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
    from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
    from zebra_agent_worker.model_call_index import ModelCallIndexer
    from zebra_agent_worker.tool_run_index import ToolRunIndexer

    stores = sqlite_control_plane_stores(tmp_path / "receipt.sqlite")
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Receipt anchor",
            user_input="anchor the acceptance on the receipt revision",
            workspace_root=tmp_path,
        )
    )
    sid = bootstrap.session.session_id
    for event in bootstrap.events:
        stores.events.append(event)

    def append(event_type, payload, actor=EventActor.HARNESS, key=None):
        events = stores.events.list_for_session(sid)
        stores.events.append(
            SessionEvent.create(
                session_id=sid,
                sequence=events[-1].sequence + 1,
                event_type=event_type,
                actor=actor,
                payload=payload,
                idempotency_key=key,
            )
        )

    append(EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1})
    append(
        EventType.SESSION_COMPLETED,
        {"attempt_number": 1, "summary": "done"},
    )
    memory_ids = []
    for index in range(2):
        memory_ids.append(str(MemoryId(uuid4())))
        append(
            EventType.MEMORY_CANDIDATE_EXTRACTED,
            {
                "memory_id": memory_ids[-1],
                "memory_type": "project_rule",
                "status": "candidate",
                "visibility": "repo",
                "text": f"rule {index}",
                "confidence": 1.0,
                "source_event_start": 0,
                "source_event_end": 4,
            },
        )
    follow_up_seq = None
    if with_follow_up:
        events = stores.events.list_for_session(sid)
        follow_up_seq = events[-1].sequence + 1
        stores.events.append(
            SessionEvent.create(
                session_id=sid,
                sequence=follow_up_seq,
                event_type=EventType.USER_MESSAGE_RECEIVED,
                actor=EventActor.USER,
                payload={"content": "the concurrent follow-up"},
            )
        )
    events = stores.events.list_for_session(sid)
    head = rebuild_session(events)
    head_workspace = rebuild_workspace(events)
    stores.sessions.save_session(head)
    stores.workspaces.save_workspace(head_workspace)

    receipt_revision = events[-1].sequence if not with_follow_up else follow_up_seq - 1
    receipt_event_ids = tuple(
        event.event_id
        for event in events
        if event.event_type is EventType.MEMORY_CANDIDATE_EXTRACTED
    )
    receipt = SimpleNamespace(session_revision=receipt_revision, event_ids=receipt_event_ids)

    at_anchor = [e for e in events if e.sequence <= 4]
    recorder = DurableHarnessEventRecorder(
        session=rebuild_session(at_anchor),
        workspace=rebuild_workspace(at_anchor),
        event_store=stores.events,
        projection_store=stores.sessions,
        workspace_store=stores.workspaces,
        model_call_indexer=ModelCallIndexer(stores.model_calls),
        tool_run_indexer=ToolRunIndexer(stores.tool_runs),
        worker_projection_transaction=SimpleNamespace(),
        worker_mutation_authority=WorkerMutationAuthority(
            deployment_namespace="receipt-test",
            session_id=sid,
            lease_fence=LeaseFence(
                control_plane_epoch=uuid4(), fencing_token=1, owner_instance_id="w"
            ),
            expected_stream_revision=4,
        ),
    )
    return stores, recorder, receipt, sid


def test_receipt_acceptance_works_for_a_plain_commit() -> None:
    """No concurrency at all: authority=4, receipt=6, stored=6."""
    import tempfile

    from zebra_agent_worker.cloud_memory_finalization import _accept_receipt

    with tempfile.TemporaryDirectory() as tmp:
        stores, recorder, receipt, sid = _build_receipt_session(Path(tmp), with_follow_up=False)
        _accept_receipt(
            recorder=recorder,
            receipt=receipt,
            event_store=stores.events,
            projection_store=stores.sessions,
            workspace_store=stores.workspaces,
        )
        events = stores.events.list_for_session(sid)
        assert recorder.session.current_sequence == events[-1].sequence
        assert recorder.workspace.current_sequence == events[-1].sequence


def test_receipt_acceptance_survives_an_ahead_projection() -> None:
    """A follow-up message at 7 advanced the stored projection to 7."""
    import tempfile

    from zebra_agent_worker.cloud_memory_finalization import _accept_receipt

    with tempfile.TemporaryDirectory() as tmp:
        stores, recorder, receipt, sid = _build_receipt_session(Path(tmp), with_follow_up=True)
        assert receipt.session_revision == 6
        _accept_receipt(
            recorder=recorder,
            receipt=receipt,
            event_store=stores.events,
            projection_store=stores.sessions,
            workspace_store=stores.workspaces,
        )
        events = stores.events.list_for_session(sid)
        # The recorder adopted the whole tail INCLUDING the follow-up and
        # agrees with the durable projection at the head (this one-shot
        # segment stays completed: a post-terminal message does not
        # re-arm it).
        assert recorder.session.current_sequence == events[-1].sequence
        assert recorder.session == stores.sessions.get_session(sid)
