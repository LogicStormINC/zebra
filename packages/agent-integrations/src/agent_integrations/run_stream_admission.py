"""Trusted Run metadata from its unique canonical accepted-command anchor."""

from agent_core.contracts.session_commands import validate_accepted_session_command
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import TaskId
from agent_core.domain.stream_admission import RunStreamAdmission, StreamMode
from agent_core.ports.agent_tasks import AgentTaskPort


def load_run_stream_admission(
    tasks: AgentTaskPort, task_id: TaskId, run_id: str
) -> RunStreamAdmission | None:
    run = tasks.read_run_header(task_id, run_id)
    if run.anchor is None:
        if run.legacy:
            return None
        raise ValueError("Run has no canonical command anchor")
    anchor = run.anchor
    page = tasks.read_event_page(
        task_id,
        anchor.task_sequence - 1,
        through_sequence=anchor.task_sequence,
        limit=1,
        max_bytes=1_048_576,
    )
    if len(page.events) != 1 or page.has_more:
        raise ValueError("Run command source is unavailable")
    entry = page.events[0]
    event = entry.event
    if (
        entry.task_sequence != anchor.task_sequence
        or entry.segment_id != anchor.segment_id
        or event.event_id != anchor.event_id
        or event.sequence != anchor.segment_sequence
        or event.event_type is not EventType.SESSION_COMMAND_ACCEPTED
    ):
        raise ValueError("Run command source conflicts with indexed anchor")
    accepted = validate_accepted_session_command(
        event.payload, session_id=entry.segment_id, idempotency_key=event.idempotency_key
    )
    if accepted.payload.get("run_id") != run_id:
        raise ValueError("Run command intent conflicts with anchor")
    admission = accepted.stream_admission
    if admission is not None and (
        (
            admission.mode is StreamMode.TRANSIENT_V2
            and (event.actor is not EventActor.USER or anchor.internal_continuation)
        )
        or admission.task_id != task_id
        or admission.run_id != run_id
    ):
        raise ValueError("Run stream metadata crosses Task or Run")
    return admission  # Absent old metadata stays legacy, including 256-character Run IDs.
