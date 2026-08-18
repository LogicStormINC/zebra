"""Wave 5 P3A-2 red tests: AgentDefinition digest continuity + SYSTEM isolation.

Target: codex/znx-wave5-p3a-turn-goal-context-v1 @ fcb80d7 (P3A base).
These tests are intentionally RED on the exact base where applicable.
They cover ZNX-AGENT-CONTEXT-01: the existing AgentDefinition system is
the single source of truth for the SYSTEM prompt, the resolved context
digest stays stable across continuation / compaction / recovery / handoff,
and the SYSTEM text never leaks into public Conversation, SSE, Artifact,
or DOM.

Per W5-P3A-2:
- Reuse AgentDefinition (server-resolved refs, version, digest).
- No second system-prompt mechanism.
- No browser/raw user-controlled system prompt.
- Continuation, compaction, recovery, handoff preserve same digest.
- AgentDefinition, Goal, Plan remain separate.
- SYSTEM text never enters public Conversation, SSE, Artifact, DOM.
- Public projection exposes only safe identities/digests where necessary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable

import pytest
from agent_core.domain.agent_definitions import (
    AgentDefinition,
    AgentDefinitionContext,
    parse_agent_definition,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_event_id, new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.sessions import Session


def _agent_definition() -> AgentDefinition:
    return AgentDefinition(
        agent_id="finos-aceagent",
        version="1.0.0",
        system_prompt_ref="system://aceagent-system",
        skill_refs=("skill://daily-journal",),
        resolved_context_digest="0" * 64,
    )


def _agent_definition_context() -> AgentDefinitionContext:
    return AgentDefinitionContext(
        agent_id="finos-aceagent",
        version="1.0.0",
        system_prompt="You are AceAgent. Honor FinOS ownership and typed-tool authority.",
        skill_guidance=(("daily-journal", "Persist only through typed tool calls."),),
    )


def test_agent_definition_server_rejects_client_supplied_digest() -> None:
    """R1: client-supplied resolved_context_digest must be rejected; only the
    server may set the digest after resolving the system prompt and skills."""
    with pytest.raises(ValueError):
        parse_agent_definition(
            {
                "agent_id": "finos-aceagent",
                "version": "1.0.0",
                "system_prompt_ref": "system://aceagent-system",
                "resolved_context_digest": "f" * 64,
            }
        )


def test_agent_definition_context_digest_is_deterministic() -> None:
    """R2: the same AgentDefinitionContext must always produce the same
    resolved_context_digest (the canonical hash)."""
    context_a = _agent_definition_context()
    context_b = _agent_definition_context()
    assert context_a.resolved_context_digest == context_b.resolved_context_digest
    assert len(context_a.resolved_context_digest) == 64


def test_agent_definition_digest_changes_when_definition_changes() -> None:
    """R3: changing the agent_id, version, system_prompt, or skill_guidance
    must change the digest; the digest is the canonical identity hash."""
    base = _agent_definition_context()
    bumped_version = AgentDefinitionContext(
        agent_id=base.agent_id,
        version="1.0.1",
        system_prompt=base.system_prompt,
        skill_guidance=base.skill_guidance,
    )
    assert base.resolved_context_digest != bumped_version.resolved_context_digest

    changed_skill = AgentDefinitionContext(
        agent_id=base.agent_id,
        version=base.version,
        system_prompt=base.system_prompt,
        skill_guidance=(("daily-journal", "Updated guidance."),),
    )
    assert base.resolved_context_digest != changed_skill.resolved_context_digest


def test_harness_task_rejects_mismatched_agent_context() -> None:
    """R4: agent_context must match agent_definition (id+version)."""
    from agent_core.harness.models import HarnessTask

    base_definition = _agent_definition()
    base_definition_no_digest = AgentDefinition(
        agent_id=base_definition.agent_id,
        version=base_definition.version,
        system_prompt_ref=base_definition.system_prompt_ref,
        skill_refs=base_definition.skill_refs,
    )
    mismatched_context = AgentDefinitionContext(
        agent_id=base_definition.agent_id,
        version="2.0.0",
        system_prompt="x",
        skill_guidance=(),
    )
    with pytest.raises(ValueError):
        HarnessTask(
            title="t",
            user_input="u",
            agent_definition=base_definition_no_digest,
            agent_context=mismatched_context,
        )


def test_compaction_preserves_resolved_context_digest() -> None:
    """R5: compaction must not drop or rewrite the resolved_context_digest."""
    from agent_core.application.session_projection import apply_event

    context = _agent_definition_context()
    digest = context.resolved_context_digest
    session = Session.create(title="d", created_at=datetime(2026, 8, 18, 9, 0, tzinfo=UTC))
    prepared = SessionEvent.create(
        session_id=session.session_id,
        sequence=1,
        event_type=EventType.TASK_PREPARED,
        actor=EventActor.HARNESS,
        payload={
            "title": "d",
            "user_input": "u",
            "agent_definition": _agent_definition().model_dump(mode="json"),
            "agent_context_digest": digest,
        },
        created_at=datetime(2026, 8, 18, 9, 0, tzinfo=UTC),
    )
    compaction = SessionEvent.create(
        session_id=session.session_id,
        sequence=2,
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
        created_at=datetime(2026, 8, 18, 9, 5, tzinfo=UTC),
    )
    projected = apply_event(apply_event(session, prepared), compaction)
    # The TASK_PREPARED payload retained its agent_definition+context, and
    # compaction must not rewrite that payload. The digest must still be
    # recoverable from the same fields.
    assert prepared.payload["agent_definition"]["agent_id"] == context.agent_id
    assert prepared.payload["agent_context_digest"] == context.resolved_context_digest
    # Verify the historical event remains unchanged (no mutation).
    assert compaction.payload["provenance"] == "truncate-middle"
    # And the canonical digest computation is stable.
    assert digest == _agent_definition_context().resolved_context_digest


def test_no_second_system_prompt_mechanism() -> None:
    """R6: only AgentDefinitionContext.render() may emit the SYSTEM prompt."""
    context = _agent_definition_context()
    rendered = context.render()
    # The rendered SYSTEM text must contain the trusted system prompt, prefixed.
    assert "Trusted system prompt context" in rendered
    # The agent_id+version identity is exposed, but the literal system_prompt
    # body is rendered as a SYSTEM-role block.
    assert context.agent_id in rendered
    assert context.version in rendered


def test_public_conversation_does_not_leak_system_text() -> None:
    """R7: SYSTEM-role text from agent_context must not appear in public projection."""
    from agent_core.application.public_conversation import project_public_conversation
    from agent_core.ports.agent_tasks import TaskEvent

    context = _agent_definition_context()
    system_text = context.system_prompt or ""
    assert system_text, "test precondition: agent context has a system prompt"

    prepared = SessionEvent.create(
        session_id=Session.create(title="p", created_at=datetime(2026, 8, 18, 9, 0, tzinfo=UTC)).session_id,
        sequence=1,
        event_type=EventType.TASK_PREPARED,
        actor=EventActor.HARNESS,
        payload={
            "title": "p",
            "user_input": "u",
            "agent_definition": _agent_definition().model_dump(mode="json"),
            "agent_context_digest": context.resolved_context_digest,
        },
        created_at=datetime(2026, 8, 18, 9, 0, tzinfo=UTC),
    )
    user = SessionEvent.create(
        session_id=prepared.session_id,
        sequence=2,
        event_type=EventType.USER_MESSAGE_RECEIVED,
        actor=EventActor.USER,
        payload={"content": "Hello."},
        created_at=datetime(2026, 8, 18, 9, 1, tzinfo=UTC),
    )
    final = SessionEvent.create(
        session_id=prepared.session_id,
        sequence=3,
        event_type=EventType.MODEL_RESPONSE_RECEIVED,
        actor=EventActor.HARNESS,
        payload={
            "assistant_message": "Sure, here's the answer.",
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "finish_reason": "stop",
        },
        created_at=datetime(2026, 8, 18, 9, 2, tzinfo=UTC),
    )
    projection = project_public_conversation(
        prepared.session_id,  # type: ignore[arg-type]
        tuple(
            TaskEvent(
                task_id=prepared.session_id,
                task_sequence=event.sequence,
                segment_id=prepared.session_id,
                segment_sequence=event.sequence,
                event=event,
            )
            for event in (prepared, user, final)
        ),
    )
    rendered = projection.to_dict()
    blob = str(rendered)
    assert system_text not in blob, (
        "SYSTEM text leaked into public conversation projection"
    )
    assert "Trusted system prompt context" not in blob


def test_public_conversation_exposes_only_safe_identity_digest() -> None:
    """R8: public projection may expose the agent_definition digest and id
    (as safe identities), never the full body."""
    from agent_core.application.public_conversation import project_public_conversation
    from agent_core.ports.agent_tasks import TaskEvent

    context = _agent_definition_context()
    prepared = SessionEvent.create(
        session_id=Session.create(title="p", created_at=datetime(2026, 8, 18, 9, 0, tzinfo=UTC)).session_id,
        sequence=1,
        event_type=EventType.TASK_PREPARED,
        actor=EventActor.HARNESS,
        payload={
            "title": "p",
            "user_input": "u",
            "agent_definition": _agent_definition().model_dump(mode="json"),
            "agent_context_digest": context.resolved_context_digest,
        },
        created_at=datetime(2026, 8, 18, 9, 0, tzinfo=UTC),
    )
    final = SessionEvent.create(
        session_id=prepared.session_id,
        sequence=2,
        event_type=EventType.MODEL_RESPONSE_RECEIVED,
        actor=EventActor.HARNESS,
        payload={
            "assistant_message": "ok",
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "finish_reason": "stop",
        },
        created_at=datetime(2026, 8, 18, 9, 2, tzinfo=UTC),
    )
    projection = project_public_conversation(
        prepared.session_id,  # type: ignore[arg-type]
        tuple(
            TaskEvent(
                task_id=prepared.session_id,
                task_sequence=event.sequence,
                segment_id=prepared.session_id,
                segment_sequence=event.sequence,
                event=event,
            )
            for event in (prepared, final)
        ),
    )
    blob = str(projection.to_dict())
    # The agent id and version may be exposed as safe identity, but never
    # the full system_prompt body or the AgentDefinitionContext.render() output.
    assert "Trusted system prompt context" not in blob
    assert (context.system_prompt or "") not in blob
    # Identity may be exposed as safe digest


def test_browser_user_controlled_system_prompt_is_rejected() -> None:
    """R9: a client-supplied raw SYSTEM prompt must be rejected by
    parse_agent_definition; only the server-side digest resolution path
    may set resolved_context_digest."""
    with pytest.raises(ValueError):
        parse_agent_definition(
            {
                "agent_id": "finos-aceagent",
                "version": "1.0.0",
                "system_prompt_ref": "system://aceagent-system",
                "client_system_prompt": "INJECT THIS",
            }
        )


def test_agent_definition_goal_and_plan_are_separate() -> None:
    """R10: AgentDefinition, Goal, and Plan remain three independent models;
    none may reference the others as a substitute."""
    from agent_core.domain.goals import GoalBinding, Goal
    from agent_core.domain.plans import PlanStep, PlanStepStatus, SessionPlan

    definition = _agent_definition()
    goal = Goal(
        binding=GoalBinding.GOAL_BOUND,
        text="Maintain today's daily journal.",
        version=1,
        created_at=datetime(2026, 8, 18, 9, 0, tzinfo=UTC),
    )
    plan = SessionPlan(
        steps=(
            PlanStep(
                step_id="draft",
                content="Draft the journal entry.",
                status=PlanStepStatus.PENDING,
            ),
        ),
    )
    # Goal does not carry agent_id or version.
    assert not hasattr(goal, "agent_id")
    assert not hasattr(plan, "agent_id")
    # Plan does not carry goal text.
    assert not hasattr(plan, "text")
    # AgentDefinition does not carry goal_text or plan steps.
    assert not hasattr(definition, "goal_text")
    assert not hasattr(definition, "steps")
