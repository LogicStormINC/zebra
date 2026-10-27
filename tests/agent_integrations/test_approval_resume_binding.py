"""Trusted approval wakeups retain the canonical Run; public markers cannot impersonate them."""

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id


@pytest.mark.parametrize("actor,internal", [(EventActor.HARNESS, True), (EventActor.USER, False)])
def test_approval_resume_preserves_run_only_with_trusted_actor(actor, internal):
    from agent_core.contracts.session_commands import SessionCommand
    from agent_core.ports.agent_tasks import TaskEvent
    from agent_integrations.ag_ui.task_run_binding import bind_task_run

    session_id = new_session_id()

    def entry(sequence, key, actor, payload):
        command = SessionCommand(
            session_id=session_id,
            kind="run" if sequence == 0 else "resume",
            expected_revision=sequence,
            idempotency_key=key,
            payload=payload,
        )
        event = SessionEvent.create(
            session_id=session_id,
            sequence=sequence,
            event_type=EventType.SESSION_COMMAND_ACCEPTED,
            actor=actor,
            payload=command.event_payload(),
        )
        return TaskEvent(
            task_id=session_id,
            task_sequence=sequence,
            segment_id=session_id,
            segment_sequence=sequence,
            event=event,
        )

    first = entry(0, "public-original", EventActor.USER, {"run_id": "original"})
    resume = entry(1, "approval-resume:original", actor, {})
    binding = bind_task_run([first, resume], "original")
    assert binding.anchor == first and binding.stop == (None if internal else 1)
