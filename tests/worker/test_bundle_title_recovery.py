"""Committed-outcome title recovery uses frozen model or safely skips it."""

from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_storage import SQLiteEventStore, SQLiteProjectionStore, SQLiteWorkspaceProjectionStore
from zebra_agent_worker.bundle_assembly import build_bundle_title_service
from zebra_agent_worker.cloud_memory_recovery import CloudMemoryFinalizationRecovery

from tests.test_bundle_assembly import settings, write_catalog
from tests.worker.test_bundle_execution import NOW, reply, seed, worker


@pytest.mark.parametrize("mode", ["compatible", "incompatible", "uncomposed"])
def test_committed_v2_title_recovery_cannot_use_process_default(tmp_path, monkeypatch, mode):
    database = tmp_path / "worker.db"
    assembly, configured, _ = write_catalog(
        tmp_path, replace(settings(), database_url=str(database))
    )
    sid, snapshot = seed(tmp_path, assembly)
    events = SQLiteEventStore(database)
    for kind, payload in (
        (EventType.HARNESS_ATTEMPT_STARTED, {"attempt_number": 1}),
        (EventType.SESSION_COMPLETED, {"attempt_number": 1, "summary": "done"}),
    ):
        events.append(
            SessionEvent.create(
                session_id=sid,
                sequence=events.list_for_session(sid)[-1].sequence + 1,
                event_type=kind,
                actor=EventActor.HARNESS,
                payload=payload,
            )
        )
    raw = events.list_for_session(sid)
    sessions, workspaces = SQLiteProjectionStore(database), SQLiteWorkspaceProjectionStore(database)
    sessions.save_session(rebuild_session(raw))
    workspaces.save_workspace(rebuild_workspace(raw))
    # Fixture only the independent memory commit; exercise real title recovery,
    # lease/Task snapshot and model HTTP adapter, not a Coverage/memory proof.
    monkeypatch.setattr(
        "zebra_agent_worker.cloud_memory_recovery.finalize_cloud_memory", lambda **kwargs: True
    )
    monkeypatch.setenv("BUNDLE_MODEL_KEY", "private-key")
    bodies = []
    active = replace(configured, model=replace(configured.model, model="changed-default"))
    if mode == "incompatible":
        active = replace(active, runtime_bundle_config=None)

    def recorder(**kwargs):
        return SimpleNamespace(
            session=kwargs["session"],
            workspace=kwargs["workspace"],
            worker_mutation_authority=object(),
            next_sequence=raw[-1].sequence + 1,
            append_event=events.append,
        )

    with httpx.Client(
        transport=httpx.MockTransport(lambda request: reply(request, bodies))
    ) as client:
        service = worker(database, active, client)
        recovery = CloudMemoryFinalizationRecovery(
            claim_service=service._claim_service,
            recorder_factory=SimpleNamespace(build=recorder),
            memory_store=object(),
            deployment_namespace="bundle-test",
            event_store=events,
            projection_store=sessions,
            workspace_store=workspaces,
            title_service_factory=lambda: pytest.fail("process-default title model used"),
            bound_title_service_factory=(
                None
                if mode == "uncomposed"
                else lambda bound: build_bundle_title_service(active, bound, client=client)
            ),
        )
        assert recovery.recover(
            sid, worker_id="title-recovery", recovered_at=NOW, lease_ttl_seconds=30
        )
    assert sessions.get_session(sid).status.value == "completed"
    assert workspaces.get_workspace(sid).definition_snapshot == snapshot
    if mode == "compatible":
        assert bodies and all(body["model"] == "alpha" for body in bodies)
        assert events.list_for_session(sid)[-1].event_type is EventType.SESSION_TITLE_UPDATED
    else:
        assert not bodies
        assert events.list_for_session(sid)[-1].event_type is EventType.SESSION_COMPLETED
