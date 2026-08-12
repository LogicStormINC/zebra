from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import apply_event as apply_session_event
from agent_core.application.workspace_projection import apply_event as apply_workspace_event
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.leases import LeaseFence
from agent_core.ports import WorkerMutationAuthority
from zebra_agent_worker.cloud_memory_finalization import finalize_cloud_memory


class _Recorder:
    def __init__(
        self,
        session: object,
        workspace: object,
        authority: WorkerMutationAuthority,
    ) -> None:
        self.session = session
        self.workspace = workspace
        self.worker_mutation_authority = authority
        self.accepted: tuple[SessionEvent, ...] = ()

    @property
    def next_sequence(self) -> int:
        return self.session.current_sequence + 1  # type: ignore[union-attr]

    def accept_committed_events(
        self,
        events: tuple[SessionEvent, ...],
        *,
        session: object,
        workspace: object,
    ) -> None:
        self.accepted = events
        self.session = session
        self.workspace = workspace


class _MemoryStore:
    def __init__(self, event_store: _EventStore, recorder: _Recorder) -> None:
        self._events = event_store
        self._recorder = recorder
        self.committed = None

    def list_for_worker(self, *_: object, **__: object) -> tuple[object, ...]:
        return ()

    def commit_worker_candidates(self, plan: object, **_: object) -> object:
        self.committed = plan
        events = plan.events  # type: ignore[union-attr]
        self._events.events.extend(events)
        session = self._recorder.session
        workspace = self._recorder.workspace
        for event in events:
            session = apply_session_event(session, event)
            workspace = apply_workspace_event(workspace, event)
        self._events.session = session
        self._events.workspace = workspace
        return SimpleNamespace(
            receipt=SimpleNamespace(event_ids=tuple(event.event_id for event in events))
        )


class _EventStore:
    def __init__(self, events: list[SessionEvent], session: object, workspace: object) -> None:
        self.events = events
        self.session = session
        self.workspace = workspace

    def list_for_session(self, _: object) -> list[SessionEvent]:
        return list(self.events)

    def read_since(self, _: object, revision: int) -> list[SessionEvent]:
        return [event for event in self.events if event.sequence > revision]


class _ProjectionStore:
    def __init__(self, events: _EventStore) -> None:
        self._events = events

    def get_session(self, _: object) -> object:
        return self._events.session


class _WorkspaceStore:
    def __init__(self, events: _EventStore) -> None:
        self._events = events

    def get_workspace(self, _: object) -> object:
        return self._events.workspace


def test_cloud_memory_finalization_commits_one_fenced_aggregate() -> None:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Cloud Memory",
            user_input="preference: use deterministic project conventions",
            workspace_root="/tmp/cloud-memory-finalization",
        )
    )
    completed = SessionEvent.create(
        session_id=bootstrap.session.session_id,
        sequence=bootstrap.session.current_sequence + 2,
        event_type=EventType.SESSION_COMPLETED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1, "summary": "done", "metadata": {}},
    )
    started = SessionEvent.create(
        session_id=bootstrap.session.session_id,
        sequence=bootstrap.session.current_sequence + 1,
        event_type=EventType.HARNESS_ATTEMPT_STARTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": 1},
    )
    session = apply_session_event(apply_session_event(bootstrap.session, started), completed)
    workspace = apply_workspace_event(
        apply_workspace_event(rebuild_workspace(list(bootstrap.events)), started), completed
    )
    authority = WorkerMutationAuthority(
        deployment_namespace="cloud-memory-test",
        session_id=session.session_id,
        lease_fence=LeaseFence(
            control_plane_epoch=uuid4(),
            fencing_token=1,
            owner_instance_id="worker-a",
        ),
        expected_stream_revision=session.current_sequence,
    )
    recorder = _Recorder(session, workspace, authority)
    event_store = _EventStore([*bootstrap.events, started, completed], session, workspace)
    memory_store = _MemoryStore(event_store, recorder)

    finalize_cloud_memory(
        recorder=recorder,  # type: ignore[arg-type]
        memory_store=memory_store,  # type: ignore[arg-type]
        deployment_namespace="cloud-memory-test",
        event_store=event_store,  # type: ignore[arg-type]
        projection_store=_ProjectionStore(event_store),  # type: ignore[arg-type]
        workspace_store=_WorkspaceStore(event_store),  # type: ignore[arg-type]
        started_at=completed.created_at,
    )

    assert memory_store.committed is not None
    assert memory_store.committed.session_id == session.session_id
    assert recorder.accepted == memory_store.committed.events
