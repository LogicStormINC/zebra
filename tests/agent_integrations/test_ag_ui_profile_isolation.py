"""Profile-bound materialization uses separate durable state and replay cursors."""

from dataclasses import replace

import pytest
from agent_core.domain.events import EventType
from agent_core.ports.agent_tasks import TaskEventPage
from agent_integrations.ag_ui.checkpoint_materializer import AgUiCheckpointMaterializer
from agent_integrations.ag_ui.checkpoint_plan import ProjectionPagePlan, checkpoint_version
from agent_integrations.ag_ui.contracts import AgUiProjectionError
from agent_integrations.ag_ui.profiles import AgUiProfileRegistry, AgUiProjectionProfile
from agent_integrations.ag_ui.projection import AgUiProjector

from tests.agent_integrations.test_ag_ui_projection_checkpoint import (
    IDENTITY,
    MemoryCheckpoints,
    event,
    plans,
)


def test_profile_materialization_and_every_frame_resume_are_isolated() -> None:
    rows = (
        event(0, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}),
        event(
            1, EventType.MODEL_RESPONSE_RECEIVED, {"model_call_id": "m", "assistant_message": "Hi"}
        ),
    )
    legacy_scope, run, decisions = plans(rows)
    port = MemoryCheckpoints(rows)
    page, plan = TaskEventPage(rows, -1, 1, 100), ProjectionPagePlan(run, decisions)
    legacy = AgUiCheckpointMaterializer(port)
    transition = legacy.prepare_page(page, plan, legacy_scope, IDENTITY)
    assert transition is not None
    port.commit_projection_page(transition)
    for name in ("agui-standard-1.0", "zebra-reliable-v2-agui-1.0"):
        profile = AgUiProjectionProfile(name, projector=AgUiProjector())
        scope = replace(legacy_scope, projector_version=checkpoint_version(run, profile))
        materializer = AgUiCheckpointMaterializer(port, profile=profile)
        assert port.read_checkpoint_head(scope).through_sequence == -1
        transition = materializer.prepare_page(page, plan, scope, IDENTITY)
        assert transition is not None
        port.commit_projection_page(transition)
        frames = list(materializer.iter_event_frames(scope, rows[1], IDENTITY, run=run))
        assert len(frames) >= 2
        for i, (cursor, _) in enumerate(frames):
            assert cursor.profile_scope is not None
            assert (
                list(
                    materializer.iter_event_frames(scope, rows[1], IDENTITY, run=run, after=cursor)
                )
                == frames[i + 1 :]
            )
            with pytest.raises(AgUiProjectionError):
                list(
                    legacy.iter_event_frames(legacy_scope, rows[1], IDENTITY, run=run, after=cursor)
                )
        assert port.read_checkpoint_head(legacy_scope).through_sequence == 1


def test_registry_only_exposes_real_bindings_and_unknown_never_downgrades() -> None:
    registry = AgUiProfileRegistry()
    assert registry.available_profiles == ()
    assert registry.select(None) is None
    for value in ("agui-standard-1.0", "zebra-reliable-v2-agui-1.0", "unknown", ""):
        with pytest.raises(AgUiProjectionError):
            registry.select(value)
    profile = AgUiProjectionProfile("agui-standard-1.0", projector=AgUiProjector())
    bound = AgUiProfileRegistry((profile,))
    assert bound.select(profile.profile_id) is profile
    assert bound.available_profiles == (profile.profile_id,)


def test_public_run_mapping_uses_canonical_continuation_and_never_execution_identity() -> None:
    from types import SimpleNamespace

    rows = (
        event(0, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}),
        event(
            1, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "approve", "payload": {"run_id": "run"}}
        ),
    )
    from tests.agent_integrations.test_ag_ui_projection_checkpoint import source_header

    scope, run, _ = plans(rows)
    continuation = replace(
        source_header(rows[1]),
        internal_continuation=True,
        command_kind="resume",
        command_run_id=None,
    )
    run = replace(run, highwater=1)
    source = SimpleNamespace(
        read_event_header=lambda task, position: run.anchor if position == 0 else continuation
    )
    profile = AgUiProjectionProfile("agui-standard-1.0", projector=AgUiProjector())
    scope = replace(scope, projector_version=checkpoint_version(run, profile))
    first = profile.protocol_run_id(source, scope, run, run.anchor)
    next_id = profile.protocol_run_id(source, scope, run, continuation)
    assert first != next_id and first != run.run_id
    assert next_id == profile.protocol_run_id(source, scope, run, continuation)
    assert first != profile.protocol_run_id(
        source, replace(scope, namespace="other"), run, run.anchor
    )
    with pytest.raises(AgUiProjectionError, match="canonical"):
        profile.protocol_run_id(
            source, scope, run, replace(continuation, event_id=rows[0].event.event_id)
        )
    with pytest.raises(AgUiProjectionError):
        profile.protocol_run_id(
            source, scope, run, replace(continuation, internal_continuation=False)
        )


def test_observer_recovery_reconstructs_the_exact_profile_binding() -> None:
    from agent_integrations.ag_ui.checkpoint_observer import AgUiCheckpointObserver

    from tests.agent_integrations.test_ag_ui_projection_checkpoint import TASK, source_header

    rows = (
        event(0, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}),
        event(
            1, EventType.MODEL_RESPONSE_RECEIVED, {"model_call_id": "m", "assistant_message": "Hi"}
        ),
    )
    scope, run, decisions = plans(rows)
    profile = AgUiProjectionProfile("agui-standard-1.0", projector=AgUiProjector())
    scope = replace(scope, projector_version=checkpoint_version(run, profile))
    port = MemoryCheckpoints(rows)
    port.read_run_header = lambda task, run_id: run
    port.read_event_header = lambda task, sequence: source_header(rows[sequence])
    materializer = AgUiCheckpointMaterializer(port, profile=profile)
    transition = materializer.prepare_page(
        TaskEventPage(rows, -1, 1, 100), ProjectionPagePlan(run, decisions), scope, IDENTITY
    )
    port.commit_projection_page(transition)
    observer = AgUiCheckpointObserver(port, namespace=scope.namespace, profile=profile)
    snapshot = observer.snapshot(TASK, IDENTITY)
    cursor = observer.recovery_cursor(snapshot, IDENTITY)
    assert cursor is not None and cursor.version == 2
    observer.validate_cursor(snapshot, IDENTITY, cursor)
    foreign = cursor.model_copy(update={"profile_scope": "f" * 64})
    with pytest.raises(AgUiProjectionError):
        observer.validate_cursor(snapshot, IDENTITY, foreign)
    coverage = replace(run, strict_coverage=True)
    port.read_run_header = lambda task, run_id: coverage
    strict_snapshot = observer.snapshot(TASK, IDENTITY)
    assert strict_snapshot.head.through_sequence == -1
    with pytest.raises(AgUiProjectionError, match="profile binding"):
        observer.validate_cursor(strict_snapshot, IDENTITY, cursor)


def test_bound_state_type_is_restored_for_both_materialization_and_replay() -> None:
    from agent_integrations.ag_ui.projection_state import ProjectionState

    calls = []

    class StandardState(ProjectionState):
        pass

    class StandardProjector(AgUiProjector):
        def project_events(self, events, identity, *, state=None):
            assert isinstance(state, StandardState)
            calls.append(type(state))
            yield from super().project_events(events, identity, state=state)

    rows = (
        event(0, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}),
        event(
            1, EventType.MODEL_RESPONSE_RECEIVED, {"model_call_id": "m", "assistant_message": "Hi"}
        ),
    )
    scope, run, decisions = plans(rows)
    profile = AgUiProjectionProfile(
        "agui-standard-1.0", projector=StandardProjector(), state_type=StandardState
    )
    scope = replace(scope, projector_version=checkpoint_version(run, profile))
    port = MemoryCheckpoints(rows)
    materializer = AgUiCheckpointMaterializer(port, profile=profile)
    transition = materializer.prepare_page(
        TaskEventPage(rows, -1, 1, 100), ProjectionPagePlan(run, decisions), scope, IDENTITY
    )
    port.commit_projection_page(transition)
    assert list(
        AgUiCheckpointMaterializer(port, profile=profile).iter_event_frames(
            scope, rows[1], IDENTITY, run=run
        )
    )
    assert len(calls) == 3
