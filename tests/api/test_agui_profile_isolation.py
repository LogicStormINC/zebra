"""Explicit profile routes, signed reconnect scope and native checkpoint recovery."""

import os
from dataclasses import replace
from types import SimpleNamespace

import pytest
from agent_integrations.ag_ui.profiles import AgUiProjectionProfile
from agent_integrations.ag_ui.projection import AgUiProjector
from zebra_agent_api.ag_ui_stream import prepare_agui_stream
from zebra_agent_api.stream_v2_cursor import StreamV2CursorCodec
from zebra_agent_api.stream_v2_reader import StreamV2Reader

from tests.api.ag_ui_checkpoint_postgres_support import pg_get_replay as _pg_get_replay

pg_get_replay = _pg_get_replay


def test_unbound_profile_rejected_before_reading_or_repairing_task():
    result = prepare_agui_stream(
        object(),
        "/agui/threads/00000000-0000-0000-0000-000000000001/runs/r/stream",
        {},
        requested_profile="agui-standard-1.0",
    )
    assert result.status_code == 409
    assert result.body["code"] == "agui_profile_unavailable"


def test_signed_cursor_has_independent_profile_revision_and_recovery_scope():
    reader = object.__new__(StreamV2Reader)
    reader.codec = StreamV2CursorCodec(b"p" * 32)
    binding = SimpleNamespace(lane="same-lane")
    profile = AgUiProjectionProfile("zebra-reliable-v2-agui-1.0", projector=AgUiProjector())
    legacy = reader.context(binding, kind="agui", token=None, full_recovery=False)
    current = reader.context(
        binding,
        kind="agui",
        token=None,
        full_recovery=False,
        profile=profile,
        profile_scope="a" * 64,
    )
    token = reader.codec.encode(replace(current.cursor, durable="position", chunk_index=2))
    assert current.cursor.scope != legacy.cursor.scope
    assert token.startswith("v2p.")
    for full in (False, True):
        with pytest.raises(ValueError):
            reader.context(
                binding,
                kind="agui",
                token=token,
                full_recovery=full,
                profile=profile,
                profile_scope="b" * 64,
            )
    for full in (False, True):
        with pytest.raises(ValueError):
            reader.context(binding, kind="agui", token=token, full_recovery=full)
    resumed = reader.context(
        binding,
        kind="agui",
        token=token,
        full_recovery=False,
        profile=profile,
        profile_scope="a" * 64,
    )
    assert resumed.cursor.chunk_index == 2


@pytest.mark.skipif(not os.environ.get("ZEBRA_HEADER_SCRATCH_DSN"), reason="isolated PG required")
def test_native_profile_consumer_and_cold_observer_use_independent_checkpoint(request):
    from agent_integrations.ag_ui.checkpoint_consumer import AgUiCheckpointConsumer
    from agent_integrations.ag_ui.checkpoint_observer import AgUiCheckpointObserver
    from agent_integrations.ag_ui.contracts import AgUiRunIdentity
    from agent_storage.postgres.projection_work import PostgresTaskProjectionWorkStore

    fixture = request.getfixturevalue("pg_get_replay")
    fixture.prepare_run()
    stores = fixture.stores()
    task = stores.tasks.task_id_for_session(fixture.session)
    identity = AgUiRunIdentity(session_id=fixture.session, thread_id=str(task), run_id="run-1")
    legacy = AgUiCheckpointObserver(
        stores.tasks, namespace=fixture.cloud.deployment_namespace
    ).snapshot(task, identity)
    profile = AgUiProjectionProfile("agui-standard-1.0", projector=AgUiProjector())
    work = PostgresTaskProjectionWorkStore(stores.tasks._database, profile.checkpoint_version())
    work.enable_projection_work()
    work.bootstrap_projection_work()
    consumer = AgUiCheckpointConsumer(
        stores.tasks, work, namespace=fixture.cloud.deployment_namespace, profile=profile
    )
    for _ in range(20):
        consumer.poll_once(budget_seconds=2)
        if not work.read_pending_projection_work() and not work.read_projection_work_repairs():
            break
    observer = AgUiCheckpointObserver(
        fixture.stores().tasks, namespace=fixture.cloud.deployment_namespace, profile=profile
    )
    snapshot = observer.snapshot(task, identity)
    assert snapshot.through == legacy.through
    assert snapshot.head.scope != legacy.head.scope
    cursor = observer.recovery_cursor(snapshot, identity)
    assert cursor is not None and cursor.profile_scope is not None
    page = observer.read_page(snapshot, snapshot.run.start - 1)
    assert page is not None
    frames = list(observer.iter_page_frames(snapshot, page, identity))
    assert frames
    for index, (position, _) in enumerate(frames):
        cold = AgUiCheckpointObserver(
            fixture.stores().tasks, namespace=fixture.cloud.deployment_namespace, profile=profile
        )
        captured = cold.snapshot(task, identity)
        cold.validate_cursor(captured, identity, position)
        assert (
            list(cold.iter_page_frames(captured, page, identity, after=position))
            == frames[index + 1 :]
        )
    observer.validate_cursor(snapshot, identity, cursor)
    from agent_integrations.ag_ui.profiles import AgUiProfileRegistry

    prepared = prepare_agui_stream(
        stores,
        f"/agui/threads/{task}/runs/run-1/stream",
        {"cursor": cursor.encode()},
        deployment_namespace=fixture.cloud.deployment_namespace,
        requested_profile=profile.profile_id,
        profile_registry=AgUiProfileRegistry((profile,)),
    )
    assert prepared.profile is profile and prepared.cursor == cursor
    old = AgUiCheckpointObserver(
        stores.tasks, namespace=fixture.cloud.deployment_namespace
    ).snapshot(task, identity)
    assert old.head == legacy.head
    with pytest.raises(ValueError):
        AgUiCheckpointObserver(
            stores.tasks, namespace=fixture.cloud.deployment_namespace
        ).validate_cursor(old, identity, cursor)


@pytest.mark.parametrize("privacy_flip", [False, True])
@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_lagging_profile_tail_reads_its_exact_queue_and_current_privacy(
    tmp_path, monkeypatch, privacy_flip, backend, request
):
    import asyncio
    import sqlite3
    from time import monotonic

    from agent_core.domain.events import EventType
    from agent_core.ports.task_projection_checkpoints import ProjectionCheckpointHead
    from agent_integrations.ag_ui.checkpoint_observer import AgUiObservationSnapshot
    from agent_integrations.ag_ui.checkpoint_plan import checkpoint_version
    from agent_integrations.ag_ui.contracts import AgUiCursor
    from agent_storage import sqlite_control_plane_stores
    from zebra_agent_api.ag_ui_checkpoint_tail import tail_checkpoint_frames
    from zebra_agent_api.ag_ui_stream import AgUiStreamContext

    from tests.agent_integrations.test_ag_ui_projection_checkpoint import (
        IDENTITY,
        TASK,
        event,
        plans,
    )

    path = tmp_path / "tail-problems.sqlite"
    if backend == "postgres":
        if not os.environ.get("ZEBRA_HEADER_SCRATCH_DSN"):
            pytest.skip("isolated PG required")
        fixture = request.getfixturevalue("pg_get_replay")
        stores = fixture.stores()
        namespace = fixture.cloud.deployment_namespace
    else:
        stores = sqlite_control_plane_stores(path)
        namespace = "local"
    profile = AgUiProjectionProfile("agui-standard-1.0", projector=AgUiProjector())
    rows = (
        event(0, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}),
        event(1, EventType.MODEL_RESPONSE_RECEIVED, {"assistant_message": "later"}),
    )
    old_scope, run, _ = plans(rows)
    scope = replace(
        old_scope, namespace=namespace, projector_version=checkpoint_version(run, profile)
    )
    ordinary = AgUiObservationSnapshot(run, ProjectionCheckpointHead(scope, 0, run.anchor.event_id))
    selected_run = replace(run, strict_coverage=privacy_flip)
    selected_scope = replace(scope, projector_version=checkpoint_version(selected_run, profile))
    selected = AgUiObservationSnapshot(
        selected_run, ProjectionCheckpointHead(selected_scope, 0, run.anchor.event_id)
    )
    statement = (
        "INSERT INTO task_projection_work (deployment_namespace,task_id,anchor_key,"
        "projector_version,run_id,anchor_sequence,requested_through,problem_code,problem_attempts) "
        "VALUES (?,?,?,?,?,0,1,'budget',1)"
    )
    values = (
        namespace,
        str(TASK),
        str(run.anchor.event_id),
        selected_scope.projector_version,
        "run",
    )
    if backend == "sqlite":
        with sqlite3.connect(path) as connection:
            connection.execute(statement, values)
    else:
        import psycopg

        with psycopg.connect(fixture.dsn) as connection:
            connection.execute(statement.replace("?", "%s"), values)
    snapshots = iter((ordinary, selected)) if privacy_flip else iter((selected,))

    class Observer:
        def __init__(self, *args, **kwargs):
            pass

        def snapshot(self, *args):
            return next(snapshots, selected)

        def validate_cursor(self, *args):
            pass

        def read_page(self, *args):
            return None

    monkeypatch.setattr("zebra_agent_api.ag_ui_checkpoint_tail.AgUiCheckpointObserver", Observer)
    cursor = AgUiCursor(
        thread_id=IDENTITY.thread_id,
        run_id="run",
        sequence=0,
        event_id=str(run.anchor.event_id),
        version=2,
        profile_scope=profile.binding_digest(scope, run),
    )
    context = AgUiStreamContext(
        stores, TASK, IDENTITY, cursor, profile=profile, deployment_namespace=namespace
    )

    class Connected:
        async def is_disconnected(self):
            return False

    async def collect(budget=2.0):
        return [
            frame
            async for frame in tail_checkpoint_frames(
                context,
                Connected(),
                monotonic() + budget,
                poll_seconds=0.001,
                keepalive_seconds=0.1,
            )
        ]

    assert asyncio.run(collect(-1)) == []
    output = "".join(asyncio.run(collect()))
    assert "projection_budget_exceeded" in output
    assert "projection_conflict" not in output
