"""Revision two is explicit and cannot replace published revision-one bindings."""

import pytest
from agent_integrations.ag_ui.contracts import AgUiProjectionError
from agent_integrations.ag_ui.profiles import AgUiProfileRegistry
from agent_integrations.ag_ui.standard_profiles import standard_profiles


def test_native_interaction_revision_is_explicit_and_keeps_revision_one():
    old = standard_profiles()
    assert {p.revision for p in old} == {1}
    registry = AgUiProfileRegistry(standard_profiles(interactions=True))
    for name in registry.available_profiles:
        assert registry.select(name).revision == 1
        assert registry.select(name, "1") == registry.select(name)
        assert registry.select(name, "2").revision == 2
    assert registry.available_revisions == {name: (1, 2) for name in registry.available_profiles}


@pytest.mark.parametrize("revision", ["", "0", "02", "+2", " 2", "2.0", "3", True, 2])
def test_revision_selection_rejects_malformed_or_unavailable_revision(revision):
    registry = AgUiProfileRegistry(standard_profiles())
    with pytest.raises(AgUiProjectionError):
        registry.select("agui-standard-1.0", revision)


def test_revision_without_profile_fails_closed():
    with pytest.raises(AgUiProjectionError):
        AgUiProfileRegistry().select(None, "2")


def test_revision_two_has_independent_checkpoint_state_and_effect_boundary():
    from uuid import UUID

    from agent_core.domain.events import EventType
    from agent_integrations.ag_ui.contracts import AgUiRunIdentity

    from tests.agent_integrations.test_ag_ui_standard_projection import source

    SID = UUID("11111111-1111-4111-8111-111111111110")

    def event(sequence, kind, payload):
        return source(sequence, kind, payload, SID)

    profile = AgUiProfileRegistry(standard_profiles(interactions=True)).select(
        "agui-standard-1.0", "2"
    )
    old = standard_profiles()[0]
    assert profile.state_type is not old.state_type
    state = profile.state_type()
    state.protocol_run_id = "agui:" + "a" * 64
    state.continuation_id = "11111111-1111-4111-8111-111111111111"
    rows = [
        event(
            1,
            EventType.TOOL_CALL_PROPOSED,
            {
                "tool_call_id": "call",
                "tool_name": "ui.open",
                "arguments": {"path": "/"},
            },
        ),
        event(
            2,
            EventType.CLIENT_EFFECT_SCHEDULED,
            {
                "client_effect_id": "11111111-1111-4111-8111-111111111112",
                "tool_call_id": "call",
                "task_id": str(SID),
                "run_id": "native",
                "surface_instance_id": "11111111-1111-4111-8111-111111111113",
                "action_name": "ui.open",
                "arguments": {"path": "/"},
                "action_contract_digest": "a" * 64,
                "client_binding_digest": "b" * 64,
                "request_digest": "c" * 64,
                "idempotency_key": "client-effect:original",
                "expires_at": "2026-10-30T00:00:00Z",
                "expected_ui_revision": 4,
                "conversation": [{"private": "not-public"}],
            },
        ),
    ]
    identity = AgUiRunIdentity(session_id=SID, thread_id=str(SID), run_id="native")
    frames = [
        f.model_dump(mode="json", by_alias=True, exclude_none=True)
        for _, result in profile.projector.project_events(rows, identity, state=state)
        for f in result
    ]
    assert [f["type"] for f in frames].count("TOOL_CALL_START") == 1
    assert frames[-1]["type"] == "RUN_FINISHED"
    assert frames[-1]["outcome"]["type"] == "success"
    assert state.public_execution == {"status": "waiting_client_effect"}
    assert state.pending_tools == {"call": "ui.open"}
    assert "not-public" not in str(frames)
    live = next(
        f["delta"][0]["value"]
        for f in frames
        if f["type"] == "STATE_DELTA" and f["delta"][0]["path"].startswith("/zebra/clientEffects/")
    )
    assert live == next(iter(state.pending_effects.values()))
    assert live["tool_call_id"] == "call"
    restored = profile.state_type.restore(state.snapshot())
    assert restored.snapshot() == state.snapshot()
    assert restored.pending_effects == state.pending_effects
    with pytest.raises(AgUiProjectionError):
        old.state_type.restore(state.snapshot())


def test_revision_two_rejection_has_exact_acknowledgement_anchor_on_cold_restore():
    from dataclasses import replace

    from agent_core.domain.events import EventType

    from tests.agent_integrations.test_ag_ui_projection_checkpoint import event, plans
    from tests.agent_integrations.test_ag_ui_standard_checkpoint import materialize

    rows = (
        event(0, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}),
        event(1, EventType.APPROVAL_REQUESTED, {"tool_call_id": "call", "reason": "approval"}),
        event(2, EventType.APPROVAL_REJECTED, {"tool_call_id": "call", "reason": "no"}),
    )
    scope, run, decisions = plans(rows)
    profile = AgUiProfileRegistry(standard_profiles(interactions=True)).select(
        "agui-standard-1.0", "2"
    )
    scope = replace(scope, projector_version=profile.checkpoint_version())
    _, _, frames = materialize(rows, scope, run, decisions, profile, 1)
    starts = [f for _, f in frames if f["type"] == "RUN_STARTED"]
    assert len(starts) == 2
    assert starts[-1]["runId"] == profile.protocol_id_for_anchor(
        scope, run, rows[-1].event.event_id
    )
    assert starts[-1]["metadata"]["zebra"]["previousProtocolRunId"] == starts[0]["runId"]
    assert frames[-1][1]["type"] == "RUN_ERROR"
    assert frames[-1][1]["code"] == "zebra_approval_rejected"


def test_revision_two_publishes_only_actual_typed_public_output_classification():
    from uuid import uuid4

    from agent_core.domain.events import EventType
    from agent_integrations.ag_ui.contracts import AgUiRunIdentity

    from tests.agent_integrations.test_ag_ui_standard_projection import VALIDATOR, source

    profile = AgUiProfileRegistry(standard_profiles(interactions=True)).select(
        "agui-standard-1.0", "2"
    )
    session = uuid4()
    event = source(
        0,
        EventType.PUBLIC_OUTPUT,
        {
            "attempt_number": 1,
            "output_id": "public-evidence",
            "kind": "result",
            "phase": "work",
            "origin": "system",
            "content": "Verified public result.",
            "meaningful": True,
            "evidence_basis": "verified_result",
            "evidence_refs": ["tool:actual"],
        },
        session,
    )
    frames = [
        frame
        for _, batch in profile.projector.project_events(
            (event,),
            AgUiRunIdentity(session_id=session, thread_id="task", run_id="agui:" + "a" * 64),
        )
        for frame in batch
    ]
    start = next(frame for frame in frames if frame.type.value == "TEXT_MESSAGE_START")
    assert start.metadata["zebra"] == {
        "version": 2,
        "kind": "result",
        "meaningful": True,
        "evidence_basis": "verified_result",
        "evidence_refs": ["tool:actual"],
    }
    for frame in frames:
        VALIDATOR.validate(frame.model_dump(mode="json", by_alias=True, exclude_none=True))


def test_revision_two_interrupt_schema_describes_real_native_responses_without_expiry():
    from uuid import uuid4

    from agent_core.domain.events import EventType
    from agent_integrations.ag_ui.contracts import AgUiRunIdentity

    from tests.agent_integrations.test_ag_ui_standard_projection import source

    session = uuid4()
    profile = AgUiProfileRegistry(standard_profiles(interactions=True)).select(
        "agui-standard-1.0", "2"
    )
    for kind, payload, field in [
        (
            EventType.APPROVAL_REQUESTED,
            {"tool_call_id": "call", "reason": "permission"},
            "decision",
        ),
        (
            EventType.CLARIFICATION_REQUESTED,
            {"clarification_id": "call", "question": "Scope?", "choices": ["One", "All"]},
            "content",
        ),
    ]:
        frames = [
            frame
            for _, batch in profile.projector.project_events(
                (source(0, kind, payload, session),),
                AgUiRunIdentity(session_id=session, thread_id="task", run_id="agui:" + "a" * 64),
            )
            for frame in batch
        ]
        interrupt = frames[-1].outcome.interrupts[0]
        assert interrupt.response_schema["properties"][field]["type"] == "string"
        assert interrupt.expires_at is None
        if field == "content":
            assert "enum" not in interrupt.response_schema["properties"][field]
            assert interrupt.metadata["zebra"]["choices"] == ["One", "All"]


def partial_publication_recording():
    """Actual producer and per-event checkpoint restoration for the official consumer."""
    from dataclasses import replace

    from agent_core.domain.events import EventType

    from tests.agent_integrations.test_ag_ui_projection_checkpoint import event, plans
    from tests.agent_integrations.test_ag_ui_standard_checkpoint import materialize

    rows = (
        event(0, EventType.SESSION_COMMAND_ACCEPTED, {"kind": "run", "payload": {"run_id": "run"}}),
        event(
            1,
            EventType.PUBLIC_OUTPUT,
            {
                "attempt_number": 1,
                "output_id": "chunk-zero",
                "kind": "commentary",
                "phase": "model_commentary",
                "origin": "model",
                "content": "Published progress.",
                "model_call_id": "model-one",
                "commentary_chunk": {"index": 0, "count": 2, "source_sha256": "a" * 64},
            },
        ),
        event(2, EventType.APPROVAL_REQUESTED, {"tool_call_id": "call", "reason": "Permission"}),
    )
    profile = AgUiProfileRegistry(standard_profiles(interactions=True)).select(
        "agui-standard-1.0", "2"
    )
    scope, run, decisions = plans(rows)
    scope = replace(scope, projector_version=profile.checkpoint_version())
    _, _, live = materialize(rows, scope, run, decisions, profile, len(rows))
    _, _, cold = materialize(rows, scope, run, decisions, profile, 1)
    assert live == cold
    frames = [frame for _, frame in live]
    return {"frames": frames, "threadId": frames[0]["threadId"], "runId": frames[0]["runId"]}


def test_revision_two_new_slice_discards_resolved_interrupt_cache_before_restoration():
    from uuid import uuid4

    from ag_ui.core import Interrupt

    profile = AgUiProfileRegistry(standard_profiles(interactions=True)).select(
        "agui-standard-1.0", "2"
    )
    state = profile.state_type()
    for index in range(3):
        state.open_interrupts[f"approval:{index}"] = Interrupt(
            id=f"approval:{index}", reason="approval_required"
        )
        state.checkpoint_interrupt_ids.add(f"approval:{index}")
        state.interrupt_ack_pending = True
        state.begin("agui:" + str(index) * 64, str(uuid4()))
        assert not state.open_interrupts and not state.checkpoint_interrupt_ids
        assert not state.interrupt_ack_pending
        state.started = True
        state = profile.state_type.restore(state.snapshot())
        assert not state.open_interrupts and not state.checkpoint_interrupt_ids


@pytest.mark.parametrize("profile_id", ["agui-standard-1.0", "zebra-reliable-v2-agui-1.0"])
@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("foreign", [False, True])
def test_human_previous_link_is_pinned_to_selected_profile_and_privacy(profile_id, strict, foreign):
    from uuid import uuid4

    from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
    from agent_core.domain.client_preparation import ClientPreparationContext
    from agent_core.domain.events import EventActor, EventType
    from agent_integrations.ag_ui.contracts import AgUiRunIdentity

    from tests.agent_integrations.test_ag_ui_standard_projection import source

    task, operation, call = uuid4(), uuid4(), uuid4()
    profile = AgUiProfileRegistry(standard_profiles(interactions=True)).select(profile_id, "2")
    context = ClientPreparationContext(
        operation_id=operation,
        client_session_id=uuid4(),
        task_id=task,
        run_id="new-native",
        projection_version=(
            "foreign:r2" if foreign else profile.checkpoint_version(coverage=strict)
        ),
        request_hash="a" * 64,
        previous_run_id="agui:" + "b" * 64,
        input={},
    )
    command = SessionCommand(
        command_id=uuid4(),
        session_id=task,
        kind=SessionCommandKind.MESSAGE,
        expected_revision=0,
        idempotency_key="agui-interaction:" + str(operation),
        payload={
            "run_id": "new-native",
            "content": "all",
            "clarification_id": str(call),
            "input": {},
            "client_preparation": context.model_dump(mode="json", exclude={"input"}),
        },
    )
    event = source(0, EventType.SESSION_COMMAND_ACCEPTED, command.event_payload(), task)
    event = event.model_copy(
        update={"actor": EventActor.USER, "idempotency_key": command.idempotency_key}
    )
    state = profile.state_type()
    state.protocol_run_id = "agui:" + "c" * 64
    state.continuation_id = str(event.event_id)
    list(
        profile.projector.project_events(
            (event,),
            AgUiRunIdentity(session_id=task, thread_id=str(task), run_id="new-native"),
            state=state,
            strict_coverage=strict,
        )
    )
    assert state.previous_protocol_run_id == (None if foreign else context.previous_run_id)
    assert (
        profile.state_type.restore(state.snapshot()).pending_clarification
        == state.pending_clarification
    )


@pytest.mark.parametrize("profile_id", ["agui-standard-1.0", "zebra-reliable-v2-agui-1.0"])
def test_strict_native_effect_and_human_sources_preserve_existing_public_privacy(profile_id):
    from uuid import uuid4

    from agent_core.domain.events import EventType
    from agent_integrations.ag_ui.contracts import AgUiRunIdentity

    from tests.agent_integrations.test_ag_ui_standard_projection import source

    task = uuid4()
    private = "private-native-arguments-answer-result-conversation"
    rows = [
        source(
            i,
            kind,
            {
                "content": private,
                "arguments": {"secret": private},
                "conversation": [{"content": private}],
                "client_effect_id": str(uuid4()),
                "tool_call_id": "private-call",
                "tool_name": "private-tool",
                "question": private,
                "result": {"secret": private},
            },
            task,
        )
        for i, kind in enumerate(
            (
                EventType.TOOL_CALL_PROPOSED,
                EventType.CLIENT_EFFECT_SCHEDULED,
                EventType.CLIENT_EFFECT_RECEIPT_ACCEPTED,
                EventType.CLARIFICATION_REQUESTED,
                EventType.CLARIFICATION_RESPONDED,
                EventType.SESSION_COMPLETED,
            )
        )
    ]
    profile = AgUiProfileRegistry(standard_profiles(interactions=True)).select(profile_id, "2")
    state = profile.state_type()
    frames = [
        frame.model_dump(mode="json", by_alias=True, exclude_none=True)
        for _, batch in profile.projector.project_events(
            rows,
            AgUiRunIdentity(session_id=task, thread_id=str(task), run_id="native"),
            state=state,
            strict_coverage=True,
        )
        for frame in batch
    ]
    assert private not in str(frames)
    assert not state.pending_effects and not state.pending_tools
    assert frames[-1]["type"] == "RUN_FINISHED"
    assert profile.state_type.restore(state.snapshot()).snapshot() == state.snapshot()
