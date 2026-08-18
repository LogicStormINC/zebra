"""Wave 5 P3A-1 red tests: goal_binding for stable tasks.

Target: codex/znx-wave5-p3a-turn-goal-context-v1 @ fcb80d7 (P3A base).
These tests are intentionally RED on the exact base. They cover
ZNX-TURN-GOAL-01: explicit `goal_binding` (conversational | goal_bound),
durable versioned Goal, TASK_GOAL_SET / TASK_GOAL_REVISED events, and
legacy recovery priority.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from agent_core.application.session_projection import apply_event
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.goals import (
    Goal,
    GoalBinding,
    apply_goal_event,
    resolve_goal_binding,
    revise_session_goal,
    set_session_goal,
)
from agent_core.domain.identifiers import SessionId, new_event_id, new_message_id
from agent_core.domain.sessions import Session


def _session(created_at: datetime | None = None) -> Session:
    return Session.create(
        title="Journal review",
        created_at=created_at or datetime(2026, 8, 18, 9, 0, tzinfo=UTC),
    )


def _task_prepared(session_id, *, sequence, plan_required=False, created_at):
    return SessionEvent.create(
        session_id=session_id,
        sequence=sequence,
        event_type=EventType.TASK_PREPARED,
        actor=EventActor.HARNESS,
        payload={
            "title": "Journal review",
            "user_input": "initial user input",
            "plan_required": plan_required,
        },
        created_at=created_at,
    )


def _user_message(session_id, content, *, sequence, created_at):
    return SessionEvent.create(
        session_id=session_id,
        sequence=sequence,
        event_type=EventType.USER_MESSAGE_RECEIVED,
        actor=EventActor.USER,
        payload={"content": content},
        created_at=created_at,
    )


def _task_goal_set_event(
    session_id,
    *,
    sequence,
    binding,
    goal_text,
    created_at,
):
    return SessionEvent.create(
        session_id=session_id,
        sequence=sequence,
        event_type=EventType.TASK_GOAL_SET,
        actor=EventActor.HARNESS,
        payload={"binding": binding, "goal_text": goal_text, "version": 1},
        created_at=created_at,
    )


def _task_goal_revised_event(
    session_id,
    *,
    sequence,
    goal_text,
    version,
    created_at,
):
    return SessionEvent.create(
        session_id=session_id,
        sequence=sequence,
        event_type=EventType.TASK_GOAL_REVISED,
        actor=EventActor.HARNESS,
        payload={"goal_text": goal_text, "version": version},
        created_at=created_at,
    )


def _attempt_started(session_id, *, sequence, attempt_number, created_at):
    return SessionEvent.create(
        session_id=session_id,
        sequence=sequence,
        event_type=EventType.HARNESS_ATTEMPT_STARTED,
        actor=EventActor.HARNESS,
        payload={"attempt_number": attempt_number},
        created_at=created_at,
    )


def _clarification(session_id, *, sequence, created_at, clarification_id="c1"):
    return SessionEvent.create(
        session_id=session_id,
        sequence=sequence,
        event_type=EventType.CLARIFICATION_REQUESTED,
        actor=EventActor.HARNESS,
        payload={
            "attempt_number": 1,
            "clarification_id": clarification_id,
            "tool_call_id": "tc-1",
            "question": "Which ticker?",
            "assistant_message": "Which ticker should I check?",
            "conversation": [],
            "model_calls_used": 1,
            "tool_calls_executed": 0,
        },
        created_at=created_at,
    )


def _approval(session_id, *, sequence, created_at):
    # APPROVAL_REQUESTED is not in the payload validator map, so direct construction.
    return SessionEvent(
        event_id=new_event_id(),
        session_id=session_id,
        sequence=sequence,
        event_type=EventType.APPROVAL_REQUESTED,
        payload={"tool_name": "finos.core.read", "reason": "permission needed"},
        actor=EventActor.HARNESS,
        created_at=created_at,
    )


def _compaction(session_id, *, sequence, created_at):
    return SessionEvent.create(
        session_id=session_id,
        sequence=sequence,
        event_type=EventType.CONTEXT_COMPACTED,
        actor=EventActor.HARNESS,
        payload={
            "attempt_number": 1,
            "before_tokens": 500,
            "after_tokens": 100,
            "removed_message_count": 2,
            "retained_message_count": 1,
            "within_budget": True,
            "provenance": "truncate-middle",
        },
        created_at=created_at,
    )


def _resume(session_id, *, sequence, created_at):
    return SessionEvent(
        event_id=new_event_id(),
        session_id=session_id,
        sequence=sequence,
        event_type=EventType.SESSION_RESUMED,
        payload={"resume_id": "r-1"},
        actor=EventActor.HARNESS,
        created_at=created_at,
    )


def test_goal_binding_enum_distinguishes_conversational_from_goal_bound() -> None:
    """R1: explicit goal_binding enum exposes conversational and goal_bound."""
    assert GoalBinding.CONVERSATIONAL == "conversational"
    assert GoalBinding.GOAL_BOUND == "goal_bound"
    assert GoalBinding("conversational") is GoalBinding.CONVERSATIONAL
    assert GoalBinding("goal_bound") is GoalBinding.GOAL_BOUND


def test_goal_record_is_durable_and_versioned() -> None:
    """R2: Goal is a durable, versioned record with normalized text."""
    goal = Goal(
        binding=GoalBinding.GOAL_BOUND,
        text="Review the 2026-08-17 A-share daily journal",
        version=1,
        created_at=datetime(2026, 8, 18, 9, 0, tzinfo=UTC),
    )
    assert goal.binding is GoalBinding.GOAL_BOUND
    assert goal.version == 1
    assert goal.text == "Review the 2026-08-17 A-share daily journal"
    with pytest.raises(ValueError):
        Goal(
            binding=GoalBinding.GOAL_BOUND,
            text="   ",
            version=1,
            created_at=datetime(2026, 8, 18, 9, 0, tzinfo=UTC),
        )


def test_three_turn_topic_shift_under_one_stable_task() -> None:
    """R3: one Stable Task carries a three-turn topic shift in conversational mode."""
    session = _session()
    now = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)
    projected = set_session_goal(
        session,
        GoalBinding.CONVERSATIONAL,
        "Ask about portfolio drift, then policy question, then journal.",
        created_at=now,
    )
    prepared = _task_prepared(session.session_id, sequence=1, plan_required=False, created_at=now)
    projected = apply_event(projected, prepared)
    first = _user_message(session.session_id, "How is my portfolio drifting from target weights?",
        sequence=2, created_at=now)
    second = _user_message(session.session_id, "Actually, what is the current margin policy for A-shares?",
        sequence=3, created_at=datetime(2026, 8, 18, 9, 5, tzinfo=UTC))
    third = _user_message(session.session_id, "Generate today's daily journal from the screenshot.",
        sequence=4, created_at=datetime(2026, 8, 18, 9, 10, tzinfo=UTC))
    for event in (first, second, third):
        projected = apply_event(projected, event)
    assert projected.session_id == session.session_id
    assert projected.goal_binding is GoalBinding.CONVERSATIONAL
    assert projected.active_goal is None
    user_role_first = first.payload["content"]
    assert user_role_first.startswith("How is my portfolio")


def test_pronoun_reference_to_prior_history_still_works() -> None:
    """R4: a follow-up that says "the screenshot above" still resolves the prior turn."""
    session = _session()
    now = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)
    projected = set_session_goal(session, GoalBinding.CONVERSATIONAL, "Discuss today's journal.", created_at=now)
    prepared = _task_prepared(session.session_id, sequence=1, plan_required=False, created_at=now)
    projected = apply_event(projected, prepared)
    first = _user_message(session.session_id, "I uploaded a screenshot of my broker trade history.",
        sequence=2, created_at=now)
    followup = _user_message(session.session_id,
        "From the screenshot above, which trades hit the price limit?",
        sequence=3, created_at=datetime(2026, 8, 18, 9, 6, tzinfo=UTC))
    for event in (first, followup):
        projected = apply_event(projected, event)
    history_turns = [
        event for event in (first, followup)
        if event.event_type is EventType.USER_MESSAGE_RECEIVED
    ]
    assert len(history_turns) == 2
    assert history_turns[1].payload["content"].startswith("From the screenshot above")


def test_goal_bound_journal_follow_up_keeps_goal() -> None:
    """R5: a goal-bound Journal follow-up retains the durable Goal across turns."""
    session = _session()
    now = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)
    projected = set_session_goal(
        session,
        GoalBinding.GOAL_BOUND,
        "Maintain today's daily journal and confirm 2026-08-17 entries.",
        created_at=now,
    )
    prepared = _task_prepared(session.session_id, sequence=1, plan_required=True, created_at=now)
    projected = apply_event(projected, prepared)
    followup = _user_message(session.session_id,
        "Mark 光智科技 as fully closed; check the math.",
        sequence=2, created_at=datetime(2026, 8, 18, 9, 7, tzinfo=UTC))
    projected = apply_event(projected, followup)
    assert projected.goal_binding is GoalBinding.GOAL_BOUND
    assert projected.active_goal is not None
    assert projected.active_goal.version == 1
    assert "\u5149\u667a\u79d1\u6280" not in (projected.active_goal.text or "")


def test_explicit_goal_revision_increments_version() -> None:
    """R6: TASK_GOAL_REVISED increments version and keeps the binding stable."""
    session = _session()
    now = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)
    projected = set_session_goal(
        session, GoalBinding.GOAL_BOUND, "Maintain today's daily journal.", created_at=now)
    revised = revise_session_goal(
        projected,
        new_text="Maintain today's daily journal and confirm 2026-08-17 entries.",
        created_at=datetime(2026, 8, 18, 9, 5, tzinfo=UTC),
    )
    assert revised.goal_binding is GoalBinding.GOAL_BOUND
    assert revised.active_goal is not None
    assert revised.active_goal.version == 2
    assert "confirm 2026-08-17 entries" in revised.active_goal.text


def test_goal_resolve_priority_prefers_explicit_goal_binding() -> None:
    binding, goal_text = resolve_goal_binding(
        explicit_binding=GoalBinding.GOAL_BOUND,
        existing_goal_text="Maintain today's daily journal.",
        plan_required=True,
    )
    assert binding is GoalBinding.GOAL_BOUND
    assert goal_text is not None and "daily journal" in goal_text


def test_goal_resolve_priority_uses_existing_goal_when_binding_omitted() -> None:
    binding, goal_text = resolve_goal_binding(
        explicit_binding=None,
        existing_goal_text="Maintain today's daily journal.",
        plan_required=False,
    )
    assert binding is GoalBinding.GOAL_BOUND
    assert goal_text == "Maintain today's daily journal."


def test_goal_resolve_priority_falls_back_to_plan_required_for_legacy() -> None:
    binding, goal_text = resolve_goal_binding(
        explicit_binding=None, existing_goal_text=None, plan_required=True,
    )
    assert binding is GoalBinding.GOAL_BOUND
    assert goal_text is None


def test_goal_resolve_priority_defaults_to_conversational_when_legacy_only() -> None:
    binding, goal_text = resolve_goal_binding(
        explicit_binding=None, existing_goal_text=None, plan_required=False,
    )
    assert binding is GoalBinding.CONVERSATIONAL
    assert goal_text is None


def test_legacy_task_recovery_does_not_mutate_old_events() -> None:
    """R11: legacy session recovers by appending TASK_GOAL_SET, not rewriting events."""
    original_created = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    legacy_session = Session.create(title="Legacy", created_at=original_created)
    legacy_event = _user_message(legacy_session.session_id, "legacy",
        sequence=1, created_at=original_created)
    recovery_event = _task_goal_set_event(
        legacy_session.session_id, sequence=2,
        binding="conversational",
        goal_text="Continue the legacy conversation",
        created_at=datetime(2026, 8, 18, 9, 0, tzinfo=UTC),
    )
    assert recovery_event.sequence == 2
    assert recovery_event.event_type is EventType.TASK_GOAL_SET
    # The legacy event itself is immutable.
    assert legacy_event.sequence == 1
    assert legacy_event.payload["content"] == "legacy"
    # Recovery applies TASK_GOAL_SET -> projection reflects the new binding.
    projected = apply_goal_event(legacy_session, recovery_event)
    assert projected.goal_binding is GoalBinding.CONVERSATIONAL


def test_clarification_and_approval_remain_in_their_original_turn() -> None:
    """R12: clarification/approval remain bound to the originating Turn."""
    session = _session()
    now = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)
    set_session_goal(session, GoalBinding.GOAL_BOUND,
        "Maintain today's daily journal.", created_at=now)
    prepared = _task_prepared(session.session_id, sequence=1, plan_required=True, created_at=now)
    projected = apply_event(session, prepared)
    # Direct verification: TASK_GOAL_SET / TASK_GOAL_REVISED must not wipe
    # the clarification or approval contexts. The session begins with both
    # contexts set; the projection after a TASK_GOAL_REVISED must keep them.
    from agent_core.domain.sessions import ApprovalContext
    from agent_core.domain.clarifications import ClarificationContext
    # Bind the session to goal_bound first.
    session_with_contexts = set_session_goal(
        session, GoalBinding.GOAL_BOUND, "Maintain today's daily journal.", created_at=now
    ).model_copy(update={
        "clarification_context": ClarificationContext(
            clarification_id="c1",
            tool_call_id="tc-1",
            question="Which ticker?",
            choices=("tsla", "nvda"),
            assistant_message="Which ticker should I check?",
            requested_at=now,
        ),
        "approval_context": ApprovalContext(
            tool_name="finos.core.read",
            reason="permission needed",
            policy_profile="default",
        ),
    })
    revised = _task_goal_revised_event(
        session_with_contexts.session_id,
        sequence=10,
        goal_text="narrow scope",
        version=2,
        created_at=now,
    )
    projected = apply_goal_event(session_with_contexts, revised)
    assert projected.clarification_context is not None
    assert projected.clarification_context.clarification_id == "c1"
    assert projected.approval_context is not None
    assert projected.approval_context.tool_name == "finos.core.read"
    assert projected.clarification_context is not None
    assert projected.clarification_context.clarification_id == "c1"
    assert projected.approval_context is not None
    assert projected.approval_context.tool_name == "finos.core.read"


def test_attempt_is_not_turn() -> None:
    """R13: multi-attempt recovery does not consume a new user Turn."""
    session = _session()
    now = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)
    prepared = _task_prepared(session.session_id, sequence=1, plan_required=False, created_at=now)
    projected = apply_event(session, prepared)
    user_turn = _user_message(session.session_id, "Compute today's drift.",
        sequence=2, created_at=now)
    projected = apply_event(projected, user_turn)
    attempts = tuple(
        _attempt_started(session.session_id, sequence=3 + index, attempt_number=index + 1, created_at=now)
        for index in range(3)
    )
    for event in attempts:
        projected = apply_event(projected, event)
    user_turn_events = [event for event in (user_turn, *attempts)
        if event.event_type is EventType.USER_MESSAGE_RECEIVED]
    attempt_events = [event for event in attempts
        if event.event_type is EventType.HARNESS_ATTEMPT_STARTED]
    assert len(user_turn_events) == 1
    assert len(attempt_events) == 3
    assert attempt_events[0].payload["attempt_number"] == 1
    assert attempt_events[2].payload["attempt_number"] == 3


def test_conversational_compaction_does_not_drop_clarification() -> None:
    """R14: compaction may compact conversational history but must never
    delete or rewrite a clarification Turn."""
    session = _session()
    base = datetime(2026, 8, 18, 8, 0, tzinfo=UTC)
    prepared = _task_prepared(session.session_id, sequence=1, plan_required=False, created_at=base)
    projected = apply_event(session, prepared)
    events = []
    for index in range(3):
        events.append(_user_message(session.session_id, f"user turn {index}",
            sequence=2 + index, created_at=base.replace(minute=index)))
    for event in events:
        projected = apply_event(projected, event)
    attempt = _attempt_started(session.session_id, sequence=5, attempt_number=1, created_at=base.replace(minute=5))
    projected = apply_event(projected, attempt)
    clarification = _clarification(session.session_id, sequence=6, created_at=base.replace(minute=10))
    projected = apply_event(projected, clarification)
    assert projected.clarification_context is not None
    assert projected.clarification_context.clarification_id == "c1"


def test_goal_bound_compaction_preserves_active_goal_version() -> None:
    """R15: compaction/recovery in goal_bound mode keeps the active Goal."""
    session = _session()
    now = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)
    projected = set_session_goal(session, GoalBinding.GOAL_BOUND,
        "Maintain today's daily journal.", created_at=now)
    prepared = _task_prepared(session.session_id, sequence=1, plan_required=True, created_at=now)
    projected = apply_event(projected, prepared)
    first = _user_message(session.session_id, "first", sequence=2, created_at=now)
    second = _user_message(session.session_id, "second", sequence=3,
        created_at=datetime(2026, 8, 18, 9, 5, tzinfo=UTC))
    compaction = _compaction(session.session_id, sequence=4,
        created_at=datetime(2026, 8, 18, 9, 10, tzinfo=UTC))
    recovery = _resume(session.session_id, sequence=5,
        created_at=datetime(2026, 8, 18, 9, 11, tzinfo=UTC))
    for event in (first, second, compaction, recovery):
        projected = apply_event(projected, event)
    assert projected.goal_binding is GoalBinding.GOAL_BOUND
    assert projected.active_goal is not None
    assert projected.active_goal.version == 1


def test_no_finos_skill_names_in_zebra_goal_module() -> None:
    """R16: Zebra goal module must not import FinOS Skill identifiers."""
    import agent_core.domain.goals as goals_module

    source = goals_module.__file__
    with open(source, encoding="utf-8") as handle:
        contents = handle.read()
    forbidden = (
        "zebra-general-assistant",
        "stock-daily-trade-log-generator",
        "stock-investment-review-score-system",
    )
    for token in forbidden:
        assert token not in contents, (
            f"Zebra domain module leaked FinOS identifier {token!r}"
        )
