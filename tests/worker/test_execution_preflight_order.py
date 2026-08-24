"""Preflight ordering: durable-close reconciliation precedes capability checks."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.turns import derive_turn_id
from agent_storage import sqlite_control_plane_stores
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.execution_preflight import prepare_execution_preflight
from zebra_agent_worker.model_call_index import ModelCallIndexer
from zebra_agent_worker.tool_run_index import ToolRunIndexer

NOW = datetime(2026, 8, 24, 16, 0, tzinfo=UTC)


def _seed_pending_close(tmp_path: Path, *, closes: bool = True, with_turn: bool = True):
    stores = sqlite_control_plane_stores(tmp_path / "preflight.sqlite")
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Preflight order",
            user_input="Do the work.",
            workspace_root=tmp_path,
        )
    )
    for event in bootstrap.events:
        stores.events.append(event)
    session_id = bootstrap.session.session_id
    events = stores.events.list_for_session(session_id)
    stores.events.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=events[-1].sequence + 1,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
        )
    )
    if with_turn:
        stores.events.append(
            SessionEvent.create(
                session_id=session_id,
                sequence=events[-1].sequence + 2,
                event_type=EventType.TURN_COMPLETED,
                actor=EventActor.HARNESS,
                payload={
                    "turn_id": str(derive_turn_id(session_id, 0)),
                    "turn_index": 0,
                    "summary": "Already done.",
                    "closes_segment": closes,
                },
            )
        )
    events = stores.events.list_for_session(session_id)
    session = rebuild_session(events)
    workspace = rebuild_workspace(events)
    stores.sessions.save_session(session)
    stores.workspaces.save_workspace(workspace)
    return stores, session, workspace, session_id


def _recorder(stores, session, workspace) -> DurableHarnessEventRecorder:
    return DurableHarnessEventRecorder(
        session=session,
        workspace=workspace,
        event_store=stores.events,
        projection_store=stores.sessions,
        workspace_store=stores.workspaces,
        model_call_indexer=ModelCallIndexer(stores.model_calls),
        tool_run_indexer=ToolRunIndexer(stores.tool_runs),
    )


def _run_preflight(stores, session, workspace, session_id, *, artifact_store: bool):
    recorded: list[DurableHarnessEventRecorder] = []

    class _Factory:
        @staticmethod
        def build(*, session, workspace, lease, ownership_check):
            recorder = _recorder(stores, session, workspace)
            recorded.append(recorder)
            return recorder

    claimed = SimpleNamespace(
        recovery=SimpleNamespace(session=session, workspace=workspace),
        lease=SimpleNamespace(fence=None),
    )
    return prepare_execution_preflight(
        recorder_factory=_Factory(),
        claimed=claimed,
        ownership_check=lambda: None,
        network_profile="setup-only",
        has_local_artifact_store=artifact_store,
        attempt_number=1,
        started_at=NOW,
        events=stores.events.list_for_session(session_id),
    )


def test_pending_completed_turn_wins_over_setup_only_capability_rejection(
    tmp_path: Path,
) -> None:
    stores, session, workspace, session_id = _seed_pending_close(tmp_path)

    recorder, outcome = _run_preflight(
        stores, session, workspace, session_id, artifact_store=False
    )

    # The durable success is reconciled to SESSION_COMPLETED; the
    # setup-only capability rejection (which WOULD fire here — no local
    # Artifact store) never appends HARNESS_ATTEMPT_STARTED/SESSION_FAILED.
    assert outcome is not None
    assert outcome.attempt_result.outcome.value == "completed"
    events = stores.events.list_for_session(session_id)
    types = [event.event_type.value for event in events]
    assert types[-1] == "session_completed"
    assert "session_failed" not in types
    # no second attempt marker was persisted after the durable close
    assert types.count("harness_attempt_started") == 1


def test_setup_only_capability_rejection_still_fires_without_pending_close(
    tmp_path: Path,
) -> None:
    # A plain RUNNING session with an open Turn and no pending close:
    # preflight falls through to the capability checks and the setup-only
    # rejection (no local Artifact store) persists SESSION_FAILED.
    stores, session, workspace, session_id = _seed_pending_close(
        tmp_path, with_turn=False
    )
    recorder, outcome = _run_preflight(
        stores, session, workspace, session_id, artifact_store=False
    )

    assert outcome is not None
    assert outcome.attempt_result.outcome.value == "failed"
    assert outcome.attempt_result.metadata["stop_reason"] == (
        "unsupported_runtime_capability"
    )
    events = stores.events.list_for_session(session_id)
    types = [event.event_type.value for event in events]
    assert "session_failed" in types
