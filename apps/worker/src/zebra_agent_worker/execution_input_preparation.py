"""Resumable execution preparation with one cumulative native I/O budget."""

from collections.abc import Callable
from time import monotonic
from typing import Any

from agent_core.domain.events import SessionEvent
from agent_core.domain.leases import WorkerLease
from agent_core.ports.agent_tasks import AgentTaskPort
from agent_core.ports.execution_inputs import (
    INPUT_VERSION,
    ExecutionInputPort,
    ExecutionToolReceipt,
    execution_tool_output,
)
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady, CheckpointStale
from agent_core.ports.worker_preparation import PreparationAdvanced
from agent_storage.postgres.task_io import task_io_deadline
from psycopg.errors import LockNotAvailable, QueryCanceled


def recover_execution_input_events(
    *,
    store: ExecutionInputPort,
    tasks: AgentTaskPort,
    lease: WorkerLease,
    max_pages: int = 8,
    expected_session_revision: int | None = None,
    ownership_check: Callable[[], None] | None = None,
) -> list[SessionEvent]:
    if type(max_pages) is not int or not 1 <= max_pages <= 32:
        raise ValueError("invalid execution preparation page budget")
    deadline = monotonic() + 2
    committed = False
    try:
        with task_io_deadline(deadline):
            if ownership_check is not None:
                ownership_check()
            task_id = tasks.task_id_for_session(lease.session_id)
            if task_id is None:
                raise CheckpointNotReady("execution inputs require indexed Task identity")
            header = tasks.read_task_header(task_id)
            if header is None or header.active_segment_id != lease.session_id:
                raise CheckpointNotReady("execution inputs require current Task Segment")
            head = store.read(lease)
            if head.through_sequence > header.current_sequence:
                raise ValueError("execution input frontier exceeds canonical Task")
            for _ in range(max_pages):
                if ownership_check is not None:
                    ownership_check()
                if monotonic() >= deadline:
                    raise TimeoutError("execution input preparation deadline exceeded")
                if head.through_sequence == header.current_sequence:
                    latest = tasks.read_task_header(task_id)
                    if latest is None or latest.active_segment_id != lease.session_id:
                        raise CheckpointNotReady("execution input Segment was superseded")
                    if latest.current_sequence < head.through_sequence:
                        raise ValueError("execution input source frontier regressed")
                    header = latest
                    if head.through_sequence == header.current_sequence:
                        return _ready_events(head, expected_session_revision)
                page = store.read_page(lease, head.through_sequence, header.current_sequence)
                try:
                    head = store.advance(lease, page)
                    committed = True
                except CheckpointStale:
                    head = store.read(lease)
            latest = tasks.read_task_header(task_id)
            if latest is None or latest.active_segment_id != lease.session_id:
                raise CheckpointNotReady("execution input Segment was superseded")
            if latest.current_sequence < head.through_sequence:
                raise ValueError("execution input source frontier regressed")
            header = latest
            if head.through_sequence == header.current_sequence:
                if ownership_check is not None:
                    ownership_check()
                return _ready_events(head, expected_session_revision)
            if committed:
                raise PreparationAdvanced(
                    f"{INPUT_VERSION}:{task_id}:{lease.session_id}",
                    head.through_sequence,
                    header.current_sequence,
                )
            raise CheckpointNotReady("execution input preparation made no durable progress")
    except PreparationAdvanced:
        raise
    except (TimeoutError, CheckpointNotReady, LockNotAvailable, QueryCanceled) as error:
        if committed:
            assert header is not None  # A confirmed advance requires an admitted header.
            raise PreparationAdvanced(
                f"{INPUT_VERSION}:{task_id}:{lease.session_id}",
                head.through_sequence,
                header.current_sequence,
            ) from error
        raise


def _ready_events(head: Any, expected_revision: int | None) -> list[SessionEvent]:
    if expected_revision is not None and head.state.session_revision != expected_revision:
        from zebra_agent_worker.execution_preflight import StaleExecutionSnapshot

        raise StaleExecutionSnapshot("execution inputs disagree with claimed Session revision")
    return list(head.state.events)


def recover_execution_tool_output(
    *,
    store: ExecutionInputPort,
    lease: WorkerLease,
    receipt: ExecutionToolReceipt,
    ownership_check: Callable[[], None],
) -> str:
    """Explicit one-event rehydration; verify exact identity and body checksum."""
    ownership_check()
    with task_io_deadline(monotonic() + 2):
        head = store.read(lease)
        if head.state.evidence is None or receipt not in head.state.evidence.tools:
            raise ValueError("tool receipt is not admitted by this execution input head")
        sequence = receipt.source_task_sequence
        page = store.read_page(lease, sequence - 1, sequence)
        if len(page.events) != 1:
            raise ValueError("tool receipt source is unavailable")
        event = page.events[0].event
        if event.session_id != lease.session_id:
            raise ValueError("tool receipt source identity/checksum conflicts")
        output = execution_tool_output(receipt, event)
        ownership_check()
        return output


class ExecutionInputEventView:
    """Read bounded exact inputs; delegate canonical writes without replaying them."""

    def __init__(
        self,
        event_store: Any,
        reader: Callable[[WorkerLease], list[SessionEvent]],
        lease: WorkerLease,
        ownership_check: Callable[[], None] | None = None,
    ) -> None:
        self._event_store, self._reader, self._lease = event_store, reader, lease
        self._ownership_check = ownership_check

    def list_for_session(self, session_id: object) -> list[SessionEvent]:
        if session_id != self._lease.session_id:
            raise ValueError("execution input reader cannot cross Session boundaries")
        if self._ownership_check is not None:
            from zebra_agent_worker.execution_preparation import finish_preparation

            return finish_preparation(lambda: self._reader(self._lease), self._ownership_check)
        return self._reader(self._lease)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._event_store, name)
