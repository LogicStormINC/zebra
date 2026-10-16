"""Fenced execution-progress recovery from native headers and bounded pages."""

import json
import logging
import traceback
from _thread import RLock
from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic

from agent_core.contracts.public_output import PublicOutputPayload
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId
from agent_core.harness.commentary_progress import accept_commentary
from agent_core.harness.model_commentary import commentary_outputs, plan_response
from agent_core.harness.models import HarnessEventDraft
from agent_core.harness.progress_recovery import validate_progress_attempt
from agent_core.harness.public_output import PublicOutputPolicy
from agent_core.ports.agent_tasks import AgentTaskPort
from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    CheckpointNotReady,
    CheckpointStale,
)
from agent_core.ports.worker_preparation import PreparationAdvanced
from agent_core.ports.worker_progress import (
    WorkerProgressHead,
    WorkerProgressScope,
    WorkerProgressState,
    WorkerProgressTimeout,
)
from agent_storage.postgres.task_io import task_io_deadline

from zebra_agent_worker.commentary_recovery import repair_commentary
from zebra_agent_worker.execution_events import ExecutionInterrupted
from zebra_agent_worker.public_output_runtime import publication_lock


@dataclass
class WorkerProgressRecovery:
    tasks: AgentTaskPort
    head: WorkerProgressHead
    ownership_check: Callable[[], None]
    max_pages: int
    _lock: RLock = field(default_factory=RLock, repr=False)

    def policy(self, fallback: PublicOutputPolicy) -> PublicOutputPolicy:
        value = self.head.state.policy_json
        return fallback if value is None else PublicOutputPolicy(**json.loads(value))

    def output_published(self, output_id: str) -> bool:
        with task_io_deadline(monotonic() + 2):
            return self.tasks.worker_output_published(self.head.scope, output_id)

    def receipts_covered(self, references: tuple[str, ...]) -> frozenset[str]:
        with task_io_deadline(monotonic() + 2):
            return self.tasks.worker_receipts_covered(self.head.scope, references)

    def catch_up(self) -> None:
        with task_io_deadline(monotonic() + 2), publication_lock(self._lock):
            self.ownership_check()
            run = self.tasks.read_latest_run_header(self.head.scope.task_id)
            if run.anchor is None or run.anchor.event_id != self.head.scope.anchor_event_id:
                raise ExecutionInterrupted("Worker progress Run was superseded")
            limit = 256
            initial_frontier = self.head.through_sequence
            for _ in range(self.max_pages):
                if self.head.through_sequence == run.highwater:
                    return
                self.ownership_check()
                page = self.tasks.read_event_page(
                    run.task_id,
                    self.head.through_sequence,
                    limit=limit,
                    max_bytes=1_048_576,
                    through_sequence=run.highwater,
                )
                try:
                    self.head = self.tasks.advance_worker_progress(self.head.scope, page)
                except CheckpointStale:
                    self.head = self.tasks.read_worker_progress(self.head.scope)
                except ValueError as exc:
                    # ponytail: a page may exceed the bounded receipt-key transition.
                    # Retry a smaller native page, never discard an Event or its keys.
                    if (
                        str(exc) != "Worker progress transition exceeds key byte bound"
                        or limit == 1
                    ):
                        raise
                    limit //= 2
            if self.head.through_sequence != run.highwater:
                if self.head.through_sequence > initial_frontier:
                    raise PreparationAdvanced(
                        f"public-progress:{self.head.scope.task_id}:{self.head.scope.run_id}",
                        self.head.through_sequence,
                        run.highwater,
                    )
                raise CheckpointNotReady(
                    "Worker progress recovered a bounded prefix; continue preparation"
                )

    def persist_with(
        self, sink: Callable[[HarnessEventDraft], None]
    ) -> Callable[[HarnessEventDraft], None]:
        if self.head.state.pending_commentary is not None:
            with task_io_deadline(monotonic() + 2), publication_lock(self._lock):
                repair_commentary(self, sink)

        def persist(event: HarnessEventDraft) -> None:
            committed, stage = False, "prepare"
            try:
                with task_io_deadline(monotonic() + 2), publication_lock(self._lock):
                    repair_commentary(self, sink)
                    if self.head.state.terminal:
                        raise ExecutionInterrupted("Worker progress Run is terminal")
                    validate_progress_attempt(
                        event.event_type, event.payload, self.head.state.attempt_number
                    )
                    if (
                        event.event_type is EventType.MODEL_RESPONSE_RECEIVED
                        and event.payload.get("public_commentary") is not None
                    ):
                        commentary_outputs(event.payload)
                        expected = plan_response(
                            event.payload, self.head.state.commentary_reserved_count
                        )
                        if event.payload["public_commentary"] != expected.get("public_commentary"):
                            raise CheckpointConflict(
                                "source commentary plan exceeds current reservation"
                            )
                    if (
                        event.event_type is EventType.PUBLIC_OUTPUT
                        and event.payload.get("phase") == "model_commentary"
                    ):
                        output = PublicOutputPayload.model_validate(event.payload)
                        if self.output_published(output.output_id):
                            return
                        accept_commentary(output, self.head.state.model_dump())
                    self.ownership_check()
                    stage = "canonical_append"
                    sink(event)
                    committed, stage = True, "checkpoint"
                    # ponytail: repair starts with a fresh catch_up; do not repeat it.
                    # A failed checkpoint never authorizes replaying the canonical append.
                    repair_commentary(self, sink)

            except TimeoutError as error:
                frames = traceback.extract_tb(error.__traceback__)
                logging.getLogger(__name__).warning(
                    "worker_progress_timeout stage=%s canonical_committed=%s location=%s",
                    stage,
                    committed,
                    ";".join(f"{f.name}:{f.lineno}" for f in frames[-6:]),
                )
                raise WorkerProgressTimeout(stage, canonical_committed=committed) from error

        return persist


def recover_worker_progress(
    *,
    tasks: AgentTaskPort,
    namespace: str,
    session_id: SessionId,
    ownership_check: Callable[[], None],
    max_pages: int = 8,
) -> WorkerProgressRecovery:
    if type(max_pages) is not int or not 1 <= max_pages <= 32:
        raise ValueError("invalid Worker progress recovery page budget")
    with task_io_deadline(monotonic() + 2):
        ownership_check()
        task_id = tasks.task_id_for_session(session_id)
        if task_id is None:
            raise CheckpointNotReady("Worker progress requires an indexed Task identity")
        run = tasks.read_latest_run_header(task_id)
        if run.anchor is None or run.control_only or run.stop is not None:
            raise CheckpointNotReady("Worker progress requires a current canonical Run identity")
        scope = WorkerProgressScope(namespace, task_id, run.run_id, run.anchor.event_id, run.start)
        try:
            head = tasks.read_worker_progress(scope)
        except CheckpointNotReady:
            head = WorkerProgressHead(scope, run.start - 1, None, WorkerProgressState())
        recovery = WorkerProgressRecovery(tasks, head, ownership_check, max_pages)
        recovery.catch_up()
        return recovery
