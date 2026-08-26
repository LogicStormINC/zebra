"""Preflight ordering: durable-close reconciliation precedes capability checks."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from agent_core.application import (
    SessionBootstrapCommand,
    SessionBootstrapService,
    current_turn,
)
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


def _seed_pending_close(
    tmp_path: Path,
    *,
    closes: bool = True,
    with_turn: bool = True,
    interaction_mode: str | None = None,
):
    stores = sqlite_control_plane_stores(tmp_path / "preflight.sqlite")
    from agent_core.domain.turns import InteractionMode

    command = SessionBootstrapCommand(
        title="Preflight order",
        user_input="Do the work.",
        workspace_root=tmp_path,
    )
    if interaction_mode is not None:
        command = SessionBootstrapCommand(
            title="Preflight order",
            user_input="Do the work.",
            workspace_root=tmp_path,
            interaction_mode=InteractionMode(interaction_mode),
        )
    bootstrap = SessionBootstrapService().build(command)
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


def test_rearm_raises_stale_when_a_turn_arrived_after_the_decision_snapshot(
    tmp_path: Path,
) -> None:
    """The claimed snapshot predates a concurrent follow-up message.

    The claimed Session/Workspace, the events argument AND the recorder's
    starting state all come from the pre-message snapshot (as in the real
    call chain); only the durable stream already contains the follow-up.
    The re-arm must raise StaleExecutionSnapshot so the caller re-recovers
    — never park or execute the stale request.
    """
    stores, session, workspace, session_id = _seed_pending_close(
        tmp_path, closes=False, interaction_mode="conversation"
    )
    events = stores.events.list_for_session(session_id)
    second_turn = str(derive_turn_id(session_id, 1))
    stores.events.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=events[-1].sequence + 1,
            event_type=EventType.USER_MESSAGE_RECEIVED,
            actor=EventActor.USER,
            payload={
                "content": "Concurrent follow-up.",
                "turn_id": second_turn,
                "turn_index": 1,
                "origin": "human",
            },
        )
    )
    fresh_events = stores.events.list_for_session(session_id)
    # The claimed state is built from the PRE-message snapshot.
    decision_snapshot = [
        event for event in fresh_events if event.sequence < fresh_events[-1].sequence
    ]
    stale_session = rebuild_session(decision_snapshot)
    stale_workspace = rebuild_workspace(decision_snapshot)
    stores.sessions.save_session(stale_session)
    stores.workspaces.save_workspace(stale_workspace)
    assert current_turn(decision_snapshot) is None

    class _Factory:
        @staticmethod
        def build(*, session, workspace, lease, ownership_check):
            return _recorder(stores, session, workspace)

    claimed = SimpleNamespace(
        recovery=SimpleNamespace(session=stale_session, workspace=stale_workspace),
        lease=SimpleNamespace(fence=None),
    )

    from zebra_agent_worker.execution_preflight import StaleExecutionSnapshot

    with pytest.raises(StaleExecutionSnapshot):
        prepare_execution_preflight(
            recorder_factory=_Factory(),
            claimed=claimed,
            ownership_check=lambda: None,
            network_profile="none",
            has_local_artifact_store=True,
            attempt_number=1,
            started_at=NOW,
            events=decision_snapshot,
            event_store=stores.events,
        )

    stored = stores.events.list_for_session(session_id)
    assert all(
        event.payload.get("reason") != "awaiting_turn_rearm" for event in stored
    )


def test_rearm_marker_retries_when_a_turn_neutral_event_wins_the_sequence(
    tmp_path: Path,
) -> None:
    """CAS conflict from a Turn-neutral event retries, no bare ValueError."""
    stores, session, workspace, session_id = _seed_pending_close(
        tmp_path, closes=False, interaction_mode="conversation"
    )

    class _Factory:
        @staticmethod
        def build(*, session, workspace, lease, ownership_check):
            recorder = _recorder(stores, session, workspace)
            original_append = recorder.append_event

            def append_with_race(event):
                if event.payload.get("reason") == "awaiting_turn_rearm" and not getattr(
                    append_with_race, "raced", False
                ):
                    append_with_race.raced = True
                    # A Turn-neutral event takes the marker's sequence first.
                    stores.events.append(
                        SessionEvent.create(
                            session_id=session_id,
                            sequence=event.sequence,
                            event_type=EventType.SESSION_TITLE_UPDATED,
                            actor=EventActor.HARNESS,
                            payload={"title": "Concurrent title"},
                        )
                    )
                return original_append(event)

            recorder.append_event = append_with_race  # type: ignore[method-assign]
            return recorder

    claimed = SimpleNamespace(
        recovery=SimpleNamespace(session=session, workspace=workspace),
        lease=SimpleNamespace(fence=None),
    )
    events = stores.events.list_for_session(session_id)

    recorder, outcome = prepare_execution_preflight(
        recorder_factory=_Factory(),
        claimed=claimed,
        ownership_check=lambda: None,
        network_profile="none",
        has_local_artifact_store=True,
        attempt_number=1,
        started_at=NOW,
        events=events,
        event_store=stores.events,
    )

    # The bounded retry appended the marker after the neutral event.
    assert outcome is not None
    assert outcome.attempt_result.metadata["stop_reason"] == "awaiting_turn_noop"
    stored = stores.events.list_for_session(session_id)
    reasons = [
        event.payload.get("reason") for event in stored if event.payload.get("reason")
    ]
    assert reasons == ["awaiting_turn_rearm"]
    sequences = [event.sequence for event in stored]
    assert sequences == list(range(len(sequences)))
    assert recorder.session.status.value == "awaiting_turn"


def test_stale_recovery_passes_the_current_lease(tmp_path: Path) -> None:
    """Cloud recovery requires the current lease: verify it is forwarded."""
    from zebra_agent_worker.claims import ClaimedSession
    from zebra_agent_worker.execution_preflight import StaleExecutionSnapshot
    from zebra_agent_worker.execution_recovery import execute_claimed_with_stale_retry

    claimed = ClaimedSession(
        lease=SimpleNamespace(fence="fence-1", session_id="sess"),
        recovery=None,
    )
    seen: dict[str, object] = {}

    class _Recovery:
        def recover_session(self, session_id, *, worker_lease=None):
            seen["session_id"] = session_id
            seen["worker_lease"] = worker_lease
            return "fresh-recovery"

    calls = {"count": 0}

    def once_inner(claimed_arg, *, started_at, ownership_check):
        calls["count"] += 1
        if calls["count"] == 1:
            raise StaleExecutionSnapshot("first run is stale")
        return "executed-fresh"

    service = SimpleNamespace(
        _recovery_service=_Recovery(),
        _execute_claimed_session_once=once_inner,
    )

    result = execute_claimed_with_stale_retry(
        service, claimed, started_at=NOW, ownership_check=lambda: None
    )

    assert result == "executed-fresh"
    assert calls["count"] == 2
    assert seen["worker_lease"] is claimed.lease


def test_second_stale_becomes_worker_execution_error() -> None:
    """The one-recovery budget converts a second stale into a typed error."""
    import pytest as _pytest
    from zebra_agent_worker.claims import ClaimedSession
    from zebra_agent_worker.execution_finalization import WorkerExecutionError
    from zebra_agent_worker.execution_preflight import StaleExecutionSnapshot
    from zebra_agent_worker.execution_recovery import execute_claimed_with_stale_retry

    claimed = ClaimedSession(
        lease=SimpleNamespace(fence="fence-2", session_id="sess-2"),
        recovery=None,
    )

    def once_inner(claimed_arg, *, started_at, ownership_check):
        raise StaleExecutionSnapshot("always stale under contention")

    service = SimpleNamespace(
        _recovery_service=SimpleNamespace(
            recover_session=lambda session_id, worker_lease=None: "fresh"
        ),
        _execute_claimed_session_once=once_inner,
    )

    with _pytest.raises(WorkerExecutionError, match="stayed stale"):
        execute_claimed_with_stale_retry(
            service, claimed, started_at=NOW, ownership_check=lambda: None
        )


def _superseded_race_stores(tmp_path: Path, *, control_event: EventType):
    """Seed a conversation close, then let the control event steal the slot."""
    stores, session, workspace, session_id = _seed_pending_close(
        tmp_path, closes=False, interaction_mode="conversation"
    )
    return stores, session, workspace, session_id, control_event


def test_concurrent_cancel_supersedes_rearm_without_escaping(tmp_path: Path) -> None:
    stores, session, workspace, session_id, control = _superseded_race_stores(
        tmp_path, control_event=EventType.SESSION_CANCELLED
    )

    class _Factory:
        @staticmethod
        def build(*, session, workspace, lease, ownership_check):
            recorder = _recorder(stores, session, workspace)
            original_append = recorder.append_event

            def append_with_race(event):
                if event.payload.get("reason") == "awaiting_turn_rearm" and not getattr(
                    append_with_race, "raced", False
                ):
                    append_with_race.raced = True
                    stores.events.append(
                        SessionEvent.create(
                            session_id=session_id,
                            sequence=event.sequence,
                            event_type=control,
                            actor=EventActor.SYSTEM,
                        )
                    )
                return original_append(event)

            recorder.append_event = append_with_race  # type: ignore[method-assign]
            return recorder

    claimed = SimpleNamespace(
        recovery=SimpleNamespace(session=session, workspace=workspace),
        lease=SimpleNamespace(fence=None),
    )
    events = stores.events.list_for_session(session_id)

    recorder, outcome = prepare_execution_preflight(
        recorder_factory=_Factory(),
        claimed=claimed,
        ownership_check=lambda: None,
        network_profile="none",
        has_local_artifact_store=True,
        attempt_number=1,
        started_at=NOW,
        events=events,
        event_store=stores.events,
    )

    # The control event won: the execution reports superseded, no crash,
    # no re-arm marker, and the recorder reflects the external status.
    assert outcome is not None
    assert outcome.attempt_result.metadata["stop_reason"] == (
        "superseded_by_control_event"
    )
    assert outcome.attempt_result.metadata["external_status"] == "cancelled"
    stored = stores.events.list_for_session(session_id)
    assert all(
        event.payload.get("reason") != "awaiting_turn_rearm" for event in stored
    )
    assert stored[-1].event_type is EventType.SESSION_CANCELLED


def test_concurrent_suspend_supersedes_rearm_without_escaping(tmp_path: Path) -> None:
    stores, session, workspace, session_id, control = _superseded_race_stores(
        tmp_path, control_event=EventType.SESSION_SUSPENDED
    )
    # SESSION_SUSPENDED requires a snapshot payload shape in its contract.
    from zebra_agent_worker.execution_preflight import prepare_execution_preflight

    class _Factory:
        @staticmethod
        def build(*, session, workspace, lease, ownership_check):
            recorder = _recorder(stores, session, workspace)
            original_append = recorder.append_event

            def append_with_race(event):
                if event.payload.get("reason") == "awaiting_turn_rearm" and not getattr(
                    append_with_race, "raced", False
                ):
                    append_with_race.raced = True
                    stores.events.append(
                        SessionEvent.create(
                            session_id=session_id,
                            sequence=event.sequence,
                            event_type=control,
                            actor=EventActor.SYSTEM,
                            payload={"reason": "external_suspend"},
                        )
                    )
                return original_append(event)

            recorder.append_event = append_with_race  # type: ignore[method-assign]
            return recorder

    claimed = SimpleNamespace(
        recovery=SimpleNamespace(session=session, workspace=workspace),
        lease=SimpleNamespace(fence=None),
    )
    events = stores.events.list_for_session(session_id)

    recorder, outcome = prepare_execution_preflight(
        recorder_factory=_Factory(),
        claimed=claimed,
        ownership_check=lambda: None,
        network_profile="none",
        has_local_artifact_store=True,
        attempt_number=1,
        started_at=NOW,
        events=events,
        event_store=stores.events,
    )

    assert outcome is not None
    assert outcome.attempt_result.metadata["external_status"] == "suspended"
    stored = stores.events.list_for_session(session_id)
    assert all(
        event.payload.get("reason") != "awaiting_turn_rearm" for event in stored
    )
