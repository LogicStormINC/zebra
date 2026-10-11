"""Bounded exact execution inputs, independent of UI and Attempt progress."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agent_core.domain.context_capsule import ContextCapsule, ContextSourceEventRange
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.leases import WorkerLease

if TYPE_CHECKING:
    from agent_core.ports.agent_tasks import TaskEvent, TaskEventPage

MAX_INPUT_BYTES = 1_048_576
MAX_INPUT_EVENTS = 2048
INPUT_VERSION = "execution-input-v3"


class ExecutionInputLimitExceeded(ValueError):
    """Exact context cannot fit: preparation fails closed, never truncates."""


class ExecutionToolReceipt(BaseModel):
    """An admitted successful historical exchange, not a pending-call authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_id: str
    tool_name: str
    arguments: dict[str, object]
    status: str
    metadata: dict[str, object]
    source_sequences: tuple[int, int, int]
    source_event_ids: tuple[UUID, UUID, UUID]
    source_task_sequence: int = Field(ge=0)
    output_sha256: str
    output_characters: int = Field(ge=0)
    artifact_uri: str


class ExecutionInputEvidence(BaseModel):
    """Derived closed-run evidence only; never install as an active ContextCapsule.

    Counters describe archived receipts, not the current Run's remaining budget.
    The canonical source remains available through the bounded page Port.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    capsule: ContextCapsule
    archived_event_count: int = Field(ge=1)
    model_request_count: int = Field(ge=0)
    model_response_count: int = Field(ge=0)
    tools: tuple[ExecutionToolReceipt, ...] = ()
    closing_event_id: UUID
    run_event_id: UUID


class ExecutionInputState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    events: tuple[SessionEvent, ...] = Field(default=(), max_length=MAX_INPUT_EVENTS)
    session_revision: int = Field(default=-1, ge=-1)
    source_hash: str = Field(default=sha256(b"").hexdigest(), pattern=r"^[a-f0-9]{64}$")
    evidence: ExecutionInputEvidence | None = None
    task_sequence_offset: int | None = Field(default=None, ge=0)

    def encoded(self) -> str:
        value = self.model_dump_json()
        if len(value.encode("utf-8")) > MAX_INPUT_BYTES:
            raise ExecutionInputLimitExceeded(
                "exact execution inputs exceed 1 MiB; preparation blocked"
            )
        return value


@dataclass(frozen=True, slots=True)
class ExecutionInputHead:
    through_sequence: int
    state: ExecutionInputState
    last_event_id: UUID | None = None

    def __post_init__(self) -> None:
        if type(self.through_sequence) is not int or not -1 <= self.through_sequence < 2**63:
            raise ValueError("invalid execution input frontier")
        if (self.through_sequence == -1) != (self.last_event_id is None):
            raise ValueError("execution input frontier identity disagrees")


def execution_tool_output(receipt: ExecutionToolReceipt, event: SessionEvent) -> str:
    """Verify a canonical completed receipt before admitting its exact body."""
    output = event.payload.get("output")
    if (
        event.event_id != receipt.source_event_ids[-1]
        or event.sequence != receipt.source_sequences[-1]
        or event.event_type is not EventType.TOOL_EXECUTION_COMPLETED
        or not isinstance(output, str)
        or sha256(output.encode()).hexdigest() != receipt.output_sha256
    ):
        raise ValueError("tool receipt source identity/checksum conflicts")
    return output


@dataclass(frozen=True, slots=True)
class ExecutionCompactionBoundary:
    """Canonical lookahead proof, admitted under the same captured highwater."""

    result: TaskEvent
    admission: TaskEvent


def fold_execution_inputs(
    head: ExecutionInputHead,
    page: TaskEventPage,
    lease: WorkerLease,
    *,
    boundary: ExecutionCompactionBoundary | None = None,
    restored: tuple[SessionEvent, ...] = (),
) -> ExecutionInputHead:
    if head.through_sequence != page.after_sequence:
        raise ValueError("execution input frontier disagrees with page")
    # Presentation is never execution evidence. All non-compactable inputs remain
    # exact; the capsule owns only proved, closed, previous-Run receipt exchanges.
    retained = tuple(
        item.event
        for item in page.events
        if item.segment_id == lease.session_id
        and item.event.event_type not in {EventType.MODEL_RESPONSE_DELTA, EventType.PUBLIC_OUTPUT}
    )
    events = tuple(sorted((*head.state.events, *restored, *retained), key=lambda e: e.sequence))
    source_hash = head.state.source_hash
    offset = head.state.task_sequence_offset
    for item in page.events:
        if item.segment_id == lease.session_id:
            current_offset = item.task_sequence - item.segment_sequence
            if offset is not None and offset != current_offset:
                raise ValueError("execution input Segment position conflicts")
            offset = current_offset
            source_hash = sha256(
                bytes.fromhex(source_hash) + item.event.model_dump_json().encode()
            ).hexdigest()
    if boundary is not None and (
        boundary.result.task_id != boundary.admission.task_id
        or (page.events and boundary.result.task_id != page.events[0].task_id)
        or boundary.admission.task_sequence > page.highwater
        or boundary.result.task_sequence >= boundary.admission.task_sequence
        or boundary.result.segment_id != lease.session_id
        or boundary.admission.segment_id != lease.session_id
        or boundary.result.event.event_type not in _RESULT_BOUNDARIES
        or boundary.result.event.actor is not EventActor.HARNESS
        or boundary.admission.event.event_type is not EventType.SESSION_COMMAND_ACCEPTED
        or boundary.admission.event.payload.get("kind") != "run"
    ):
        raise ValueError("execution evidence boundary conflicts with captured source")
    revisions = [
        item.segment_sequence for item in page.events if item.segment_id == lease.session_id
    ]
    revision = revisions[-1] if revisions else head.state.session_revision
    events, evidence = _compact_closed_receipts(
        events,
        head.state.evidence,
        source_hash,
        boundary,
        revision,
        offset,
    )
    if len(events) > MAX_INPUT_EVENTS:
        raise ExecutionInputLimitExceeded(
            "exact execution inputs exceed 2048 events; preparation blocked"
        )
    state = ExecutionInputState(
        events=events,
        session_revision=revision,
        source_hash=source_hash,
        evidence=evidence,
        task_sequence_offset=offset,
    )
    state.encoded()
    if any(a.sequence >= b.sequence for a, b in zip(events, events[1:], strict=False)):
        raise ValueError("execution input source order conflicts")
    last = page.events[-1].event.event_id if page.events else head.last_event_id
    return ExecutionInputHead(page.next_sequence, state, last)


_RESULT_BOUNDARIES = {
    EventType.TURN_COMPLETED,
    EventType.TURN_FAILED,
    EventType.TURN_CANCELLED,
    EventType.SESSION_COMPLETED,
    EventType.SESSION_FAILED,
    EventType.SESSION_CANCELLED,
}
_MODEL_PAIR = (EventType.MODEL_REQUEST_STARTED, EventType.MODEL_RESPONSE_RECEIVED)
_TOOL_EXCHANGE = (
    EventType.TOOL_CALL_PROPOSED,
    EventType.TOOL_EXECUTION_STARTED,
    EventType.TOOL_EXECUTION_COMPLETED,
)


def _groups(
    events: tuple[SessionEvent, ...],
    kinds: tuple[EventType, ...],
    key: str,
) -> list[tuple[SessionEvent, ...]]:
    groups: dict[tuple[int, str], list[SessionEvent]] = {}
    for event in events:
        number, identity = event.payload.get("attempt_number"), event.payload.get(key)
        if (
            event.event_type in kinds
            and type(number) is int
            and number > 0
            and (isinstance(identity, str) and identity.strip())
        ):
            groups.setdefault((number, identity), []).append(event)
    # Ambiguous duplicate IDs, incomplete exchanges, reordered or historical
    # untyped receipts stay exact. No guessed terminal state or last-N cutoff.
    return [
        tuple(group)
        for group in groups.values()
        if tuple(event.event_type for event in group) == kinds
        and all(event.actor in {EventActor.HARNESS, EventActor.TOOL} for event in group)
    ]


def _compact_closed_receipts(
    events: tuple[SessionEvent, ...],
    previous: ExecutionInputEvidence | None,
    source_hash: str,
    boundary: ExecutionCompactionBoundary | None,
    revision: int,
    offset: int | None,
) -> tuple[tuple[SessionEvent, ...], ExecutionInputEvidence | None]:
    anchors = [
        event.sequence
        for event in events
        if event.event_type is EventType.SESSION_COMMAND_ACCEPTED
        and event.payload.get("kind") == "run"
        and isinstance(event.payload.get("payload"), dict)
        and isinstance(event.payload["payload"].get("run_id"), str)
        and event.payload["payload"]["run_id"].strip()
    ]
    if boundary is not None:
        anchors.append(boundary.admission.event.sequence)
    if not anchors:
        return events, previous
    closed = [
        event
        for event in events
        if event.event_type in _RESULT_BOUNDARIES
        and event.sequence < anchors[-1]
        and event.actor is EventActor.HARNESS
    ]
    if boundary is not None:
        closed.append(boundary.result.event)
    if not closed:
        return events, previous
    protected_ids = {
        event.payload.get("tool_call_id")
        for event in events
        if event.event_type
        in {
            EventType.APPROVAL_REQUESTED,
            EventType.APPROVAL_GRANTED,
            EventType.APPROVAL_REJECTED,
            EventType.CLARIFICATION_REQUESTED,
            EventType.CLARIFICATION_RESPONDED,
        }
        and isinstance(event.payload.get("tool_call_id"), str)
    }
    if previous is not None:
        restored_ids = {event.event_id for event in events}
        recovered = tuple(tool for tool in previous.tools if tool.call_id in protected_ids)
        if any(not set(tool.source_event_ids) <= restored_ids for tool in recovered):
            raise ExecutionInputLimitExceeded(
                "referenced archived exchange requires exact rehydration"
            )
        if recovered:
            remaining = tuple(tool for tool in previous.tools if tool not in recovered)
            count = previous.archived_event_count - 3 * len(recovered)
            previous = (
                previous.model_copy(
                    update={
                        "tools": remaining,
                        "archived_event_count": count,
                        "capsule": previous.capsule.model_copy(
                            update={
                                "completed_actions": tuple(
                                    f"{tool.tool_name}:{tool.status}:{tool.call_id}"
                                    for tool in remaining
                                ),
                                "artifact_refs": tuple(
                                    dict.fromkeys(tool.artifact_uri for tool in remaining)
                                ),
                            }
                        ),
                    }
                )
                if count
                else None
            )
    closing = max(closed, key=lambda event: event.sequence)
    prefix = tuple(event for event in events if event.sequence < closing.sequence)
    models = [
        pair
        for pair in _groups(prefix, _MODEL_PAIR, "model_call_id")
        if pair[0].payload.get("purpose") != "public_expression"
        and pair[1].payload.get("response_stage") != "public_expression"
        and isinstance(pair[1].payload.get("assistant_message"), str)
        and type(pair[1].payload.get("tool_call_count")) is int
        and pair[1].payload["tool_call_count"] >= 0
        and not pair[1].payload.get("normalized_error")
    ]
    tools: list[ExecutionToolReceipt] = []
    tool_groups = []
    for proposed, started, completed in _groups(prefix, _TOOL_EXCHANGE, "tool_call_id"):
        payload = completed.payload
        call_id, name = payload["tool_call_id"], payload.get("tool_name")
        if (
            call_id in protected_ids
            or not isinstance(name, str)
            or not name.strip()
            or proposed.payload.get("tool_name") != name
            or started.payload.get("tool_name") != name
            or not isinstance(proposed.payload.get("arguments"), dict)
            or payload.get("status") not in {"executed", "succeeded"}
            or not isinstance(payload.get("output"), str)
            or not isinstance(payload.get("metadata"), dict)
        ):
            continue
        output, metadata = payload["output"], payload["metadata"]
        checksum = sha256(output.encode()).hexdigest()
        if metadata.get("output_sha256") not in (None, checksum):
            continue
        uri = metadata.get("artifact_uri")
        tools.append(
            ExecutionToolReceipt(
                call_id=call_id,
                tool_name=name,
                arguments=proposed.payload["arguments"],
                status=payload["status"],
                metadata=metadata,
                source_sequences=(proposed.sequence, started.sequence, completed.sequence),
                source_event_ids=(proposed.event_id, started.event_id, completed.event_id),
                source_task_sequence=completed.sequence + (offset or 0),
                output_sha256=checksum,
                output_characters=len(output),
                artifact_uri=uri
                if isinstance(uri, str) and uri.strip()
                else f"event://{completed.session_id}/{completed.sequence}",
            )
        )
        tool_groups.append((proposed, started, completed))
    removed = {event.event_id for group in (*models, *tool_groups) for event in group}
    if not removed:
        return events, previous
    users = tuple(
        dict.fromkeys(
            event.payload["content"]
            for event in events
            if event.event_type is EventType.USER_MESSAGE_RECEIVED
            and isinstance(event.payload.get("content"), str)
            and event.payload["content"].strip()
        )
    )
    if not users:
        return events, previous
    old = previous.capsule if previous else None
    decisions = tuple(
        dict.fromkeys(
            (
                *(old.decisions if old else ()),
                *(pair[1].payload["assistant_message"] for pair in models),
            )
        )
    )
    all_tools = (*(previous.tools if previous else ()), *tools)
    # This is receipt evidence, NOT a conversation summary or lifecycle authority.
    # No assistant/user text is sliced, and no pending tool is inferred complete.
    capsule = ContextCapsule(
        capsule_id=f"exec-evidence-{source_hash[:24]}",
        objective=users[-1],
        protected_user_constraints=users,
        decisions=decisions,
        completed_actions=tuple(
            f"{tool.tool_name}:{tool.status}:{tool.call_id}" for tool in all_tools
        ),
        artifact_refs=tuple(dict.fromkeys(tool.artifact_uri for tool in all_tools)),
        source_hash=source_hash,
        source_event_range=ContextSourceEventRange(start_sequence=0, end_sequence=revision),
        scope=("closed_previous_run_receipts_only",),
        profile="zebra-execution-evidence-v1",
        immediate_next=users[-1],
        confidence=1,
        known_omissions=(
            "Archived model telemetry/order remains canonical; distinct exact assistant texts "
            "are retained without repetition counts.",
            "Historical tool output bodies require checksum-verified source rehydration.",
            "This capsule is not authority for pending calls, approvals or current Run budgets.",
        ),
        created_at=events[-1].created_at,
    )
    evidence = ExecutionInputEvidence(
        capsule=capsule,
        archived_event_count=(previous.archived_event_count if previous else 0) + len(removed),
        model_request_count=(previous.model_request_count if previous else 0) + len(models),
        model_response_count=(previous.model_response_count if previous else 0) + len(models),
        tools=all_tools,
        closing_event_id=closing.event_id,
        run_event_id=boundary.admission.event.event_id
        if boundary is not None
        else next(event.event_id for event in reversed(events) if event.sequence == anchors[-1]),
    )
    return tuple(event for event in events if event.event_id not in removed), evidence


class ExecutionInputPort(Protocol):
    @property
    def namespace(self) -> str: ...

    def read(self, lease: WorkerLease) -> ExecutionInputHead: ...

    def advance(self, lease: WorkerLease, page: TaskEventPage) -> ExecutionInputHead: ...

    def read_page(self, lease: WorkerLease, after: int, through: int) -> TaskEventPage: ...
