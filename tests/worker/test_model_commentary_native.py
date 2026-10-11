"""Real PostgreSQL source gap repair and the actual atomic Worker lease fence."""

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import apply_event
from agent_core.application.workspace_projection import apply_event as apply_workspace_event
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.leases import LeaseLostError
from agent_core.harness.model_commentary import commentary_outputs, plan_response
from agent_core.harness.models import HarnessEventDraft
from agent_core.harness.public_output import ProgressiveEventSink, PublicOutputPolicy
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_storage import (
    PostgresAgentTaskStore,
    PostgresEventStore,
    PostgresProjectionStore,
    bootstrap_control_plane_epoch,
)
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.leases import PostgresLeaseStore
from agent_storage.postgres.workspaces import PostgresWorkspaceProjectionStore
from zebra_agent_worker.progress_recovery import recover_worker_progress

from tests.agent_core.test_model_commentary import source
from tests.agent_storage.test_postgres_task_projection_checkpoints import checkpoint_dsn

native_dsn = checkpoint_dsn
NS = "native-model-commentary"


def native_state(dsn):
    bootstrap_control_plane_epoch(dsn, deployment_namespace=NS)
    boot = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Commentary gap", user_input="continue", workspace_root=Path("/tmp/commentary-qa")
        )
    )
    events = PostgresEventStore(dsn, deployment_namespace=NS)
    for event in boot.events:
        events.append(event)
    sessions = PostgresProjectionStore(dsn, deployment_namespace=NS)
    workspaces = PostgresWorkspaceProjectionStore(dsn, deployment_namespace=NS)
    sessions.save_session(boot.session)
    workspace = workspaces.save_workspace(rebuild_workspace(list(boot.events)))
    tasks = PostgresAgentTaskStore(dsn, deployment_namespace=NS)
    task = tasks.ensure_for_session(boot.session.session_id)
    while not tasks.backfill_event_positions(task.task_id):
        pass
    while not tasks.backfill_replay_headers(task.task_id):
        pass
    leases = PostgresLeaseStore(dsn, deployment_namespace=NS)
    lease = leases.acquire(
        boot.session.session_id, owner_instance_id="commentary-owner", ttl=timedelta(seconds=60)
    )
    state = SimpleNamespace(
        session=boot.session,
        workspace=workspace,
        rows=[],
        tasks=tasks,
        database=PostgresDatabase(dsn, deployment_namespace=NS),
        lease=lease,
        events=events,
        authority=WorkerMutationAuthority(
            deployment_namespace=NS,
            session_id=lease.session_id,
            lease_fence=lease.fence,
            expected_stream_revision=boot.session.current_sequence,
        ),
    )

    def append(draft):
        event = SessionEvent.create(
            session_id=lease.session_id,
            sequence=state.session.current_sequence + 1,
            event_type=draft.event_type,
            actor=draft.actor,
            payload=draft.payload,
        )
        result = workspaces.commit_worker_event(
            event,
            apply_event(state.session, event),
            apply_workspace_event(state.workspace, event),
            authority=state.authority,
        )
        state.session, state.workspace = result.session, result.workspace
        state.authority = state.authority.model_copy(
            update={"expected_stream_revision": result.event.sequence}
        )
        state.rows.append(draft)

    state.append = append
    command = SessionCommand(
        session_id=lease.session_id,
        kind=SessionCommandKind.RUN,
        expected_revision=boot.session.current_sequence,
        idempotency_key="commentary-run",
        payload={"run_id": "commentary-run"},
    )
    append(
        HarnessEventDraft(
            EventType.SESSION_COMMAND_ACCEPTED, EventActor.USER, command.event_payload()
        )
    )
    return state


def restored(state):
    return recover_worker_progress(
        tasks=state.tasks,
        namespace=NS,
        session_id=state.lease.session_id,
        ownership_check=lambda: None,
    )


@pytest.mark.parametrize("lost_commit_response", [False, True])
def test_native_source_gap_exact_once_and_real_index_membership(
    native_dsn, monkeypatch, lost_commit_response
):
    state = native_state(native_dsn)
    payload = plan_response(source("公开 🐎\n" * 1001), 0)
    state.append(HarnessEventDraft(EventType.MODEL_RESPONSE_RECEIVED, EventActor.HARNESS, payload))
    monkeypatch.setattr(state.events, "list_for_session", lambda _: pytest.fail("whole history"))
    recovery = restored(state)
    if lost_commit_response:

        def unknown(draft):
            state.append(draft)
            raise TimeoutError("commit acknowledgement lost")

        with pytest.raises(TimeoutError):
            recovery.persist_with(unknown)
        recovery = restored(state)
    recovery.persist_with(state.append)
    outputs = [d for d in state.rows if d.event_type is EventType.PUBLIC_OUTPUT]
    assert outputs == list(commentary_outputs(payload))
    assert recovery.head.state.pending_commentary is None
    assert recovery.head.state.commentary_published_count == len(outputs)
    assert recovery.head.state.published_count == 0
    assert all(recovery.output_published(str(d.payload["output_id"])) for d in outputs)
    before = len(state.rows)
    restored(state).persist_with(state.append)
    assert len(state.rows) == before


def test_native_expired_fence_between_chunks_cannot_publish_or_skip_index(native_dsn):
    state = native_state(native_dsn)
    payload = plan_response(source("x" * 4001), 0)
    state.append(HarnessEventDraft(EventType.MODEL_RESPONSE_RECEIVED, EventActor.HARNESS, payload))
    recovery = restored(state)

    def expire_after_chunk(draft):
        state.append(draft)
        with state.database.connect_task_io() as c:
            c.execute(
                "UPDATE worker_leases SET acquired_at=clock_timestamp()-interval '3 seconds', "
                "heartbeat_at=clock_timestamp()-interval '2 seconds', "
                "expires_at=clock_timestamp()-interval '1 second' "
                "WHERE deployment_namespace=%s AND session_id=%s",
                (NS, state.lease.session_id),
            )

    with pytest.raises(LeaseLostError):
        recovery.persist_with(expire_after_chunk)
    again = restored(state)
    assert again.head.state.commentary_published_count == 1
    assert again.head.state.pending_commentary.next_index == 1
    chunks = commentary_outputs(payload)
    assert again.output_published(str(chunks[0].payload["output_id"]))
    assert not again.output_published(str(chunks[1].payload["output_id"]))
    with pytest.raises(LeaseLostError):
        again.persist_with(state.append)
    assert len([d for d in state.rows if d.event_type is EventType.PUBLIC_OUTPUT]) == 1


def test_native_live_producer_automatic_gap_repair_dedup_and_facts_quota(native_dsn):
    state = native_state(native_dsn)
    recovered = restored(state)
    sink = ProgressiveEventSink(
        recovered.persist_with(state.append),
        user_input="读取来源",
        policy=PublicOutputPolicy(max_outputs=1),
        recovery_state=recovered.head.state,
        output_published=recovered.output_published,
    )
    try:
        sink(
            HarnessEventDraft(
                EventType.MODEL_RESPONSE_RECEIVED, EventActor.HARNESS, source("中" * 4000 + " \n")
            )
        )
        sources = [d for d in state.rows if d.event_type is EventType.MODEL_RESPONSE_RECEIVED]
        assert (
            len(sources) == 1
            and sources[0].payload["public_commentary"]["disposition"] == "admitted"
        )
        chunks = [d for d in state.rows if d.payload.get("phase") == "model_commentary"]
        assert len(chunks) == 2 and chunks[-1].payload["content"] == " \n"
        assert "".join(d.payload["content"] for d in chunks) == "中" * 4000 + " \n"
        assert sink.publish(
            "verified",
            "result",
            "evidence",
            "Verified fact",
            meaningful=True,
            evidence_basis="verified_result",
            evidence_refs=["receipt:1"],
        )
        assert recovered.head.state.published_count == 1
        assert recovered.head.state.commentary_reserved_count == 2
        assert recovered.head.state.commentary_published_count == 2
        assert recovered.head.state.pending_commentary is None
    finally:
        sink.close()
