"""Read-only, bounded observation of a shared durable AG-UI projection."""

from collections.abc import Iterator
from dataclasses import dataclass

from ag_ui.core import Event
from agent_core.domain.identifiers import TaskId
from agent_core.ports.agent_tasks import AgentTaskPort, TaskEventPage
from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    CheckpointNotReady,
    ProjectionCheckpointHead,
    ProjectionScope,
)
from agent_core.ports.task_replay import TaskRunHeader

from agent_integrations.ag_ui.checkpoint_materializer import AgUiCheckpointMaterializer
from agent_integrations.ag_ui.checkpoint_plan import AG_UI_CHECKPOINT_VERSION
from agent_integrations.ag_ui.contracts import AgUiCursor, AgUiProjectionError, AgUiRunIdentity


@dataclass(frozen=True, slots=True)
class AgUiObservationSnapshot:
    run: TaskRunHeader
    head: ProjectionCheckpointHead

    @property
    def bound(self) -> bool:
        return not self.run.control_only and (self.run.legacy or self.run.anchor is not None)

    @property
    def through(self) -> int:
        stop = self.run.stop - 1 if self.run.stop is not None else self.run.highwater
        return min(stop, self.head.through_sequence, self.run.highwater)


class AgUiCheckpointObserver:
    """Never hydrates a Task, materializes checkpoints, or executes commands."""

    def __init__(self, tasks: AgentTaskPort, *, namespace: str) -> None:
        self.tasks, self.namespace = tasks, namespace
        self.materializer = AgUiCheckpointMaterializer(tasks)

    def snapshot(self, task_id: TaskId, identity: AgUiRunIdentity) -> AgUiObservationSnapshot:
        if str(task_id) != identity.thread_id:
            raise AgUiProjectionError("observation belongs to another Task")
        run = self.tasks.read_run_header(task_id, identity.run_id)
        if run.task_id != task_id or run.run_id != identity.run_id:
            raise CheckpointConflict("observation Run belongs to another Task/run")
        scope = ProjectionScope(
            self.namespace, task_id, run.anchor.event_id if run.anchor else None,
            AG_UI_CHECKPOINT_VERSION,
        )
        # A newly admitted command may not have reached its source index yet.
        # Do not inspect a legacy projection or another Run while waiting.
        head = (
            ProjectionCheckpointHead(scope)
            if run.control_only or (not run.legacy and run.anchor is None)
            else self.tasks.read_checkpoint_head(scope)
        )
        if head.through_sequence > run.highwater:
            refreshed = self.tasks.read_run_header(task_id, identity.run_id)
            if refreshed.task_id != task_id or refreshed.run_id != identity.run_id:
                raise CheckpointConflict("refreshed observation belongs to another Task/run")
            if (
                refreshed.anchor != run.anchor or refreshed.start != run.start
                or refreshed.legacy != run.legacy or refreshed.control_only != run.control_only
            ):
                raise CheckpointNotReady("observation Run changed while capturing its head")
            run = refreshed
        if head.scope != scope or head.through_sequence > run.highwater:
            raise CheckpointConflict("observation head conflicts with captured source coverage")
        return AgUiObservationSnapshot(run, head)

    def validate_cursor(
        self,
        snapshot: AgUiObservationSnapshot,
        identity: AgUiRunIdentity,
        cursor: AgUiCursor | None,
    ) -> None:
        """Preflight uses indexed metadata only, including exact partial frames."""
        if cursor is None:
            return
        run = snapshot.run
        if (
            not snapshot.bound
            or cursor.thread_id != identity.thread_id
            or cursor.run_id != identity.run_id
            or not max(0, run.start - 1) <= cursor.sequence <= run.highwater
            or (run.stop is not None and cursor.sequence >= run.stop)
        ):
            raise AgUiProjectionError("cursor is outside the requested Task/run")
        source = self.tasks.read_event_header(run.task_id, cursor.sequence)
        if source is None or str(source.event_id) != cursor.event_id:
            raise AgUiProjectionError("cursor does not identify a canonical Task Event")
        if source.task_id != run.task_id or source.task_sequence != cursor.sequence:
            raise CheckpointConflict("cursor source locator conflicts with its Task position")
        if cursor.frame_index is None:
            return
        if cursor.sequence < run.start:
            raise AgUiProjectionError("cursor frame precedes its Run")
        header = self.tasks.read_event_projection_header(snapshot.head.scope, cursor.sequence)
        if header is None:
            raise CheckpointNotReady("cursor frame checkpoint is not ready")
        if (
            (header.event_id, header.segment_id, header.segment_sequence)
            != (source.event_id, source.segment_id, source.segment_sequence)
            or header.task_sequence != source.task_sequence
        ):
            raise CheckpointConflict("cursor frame conflicts with canonical source")
        if not header.eligible or cursor.frame_index >= header.frame_count:
            raise AgUiProjectionError("cursor frame is outside its durable Event")

    def recovery_cursor(
        self, snapshot: AgUiObservationSnapshot, identity: AgUiRunIdentity,
    ) -> AgUiCursor | None:
        header = snapshot.head.latest_eligible
        if (
            not snapshot.bound or header is None
            or not snapshot.run.start <= header.task_sequence <= snapshot.through
        ):
            return None
        return AgUiCursor(
            thread_id=identity.thread_id, run_id=identity.run_id,
            sequence=header.task_sequence, event_id=str(header.event_id),
            frame_index=header.frame_count - 1 if header.frame_count else None,
        )

    def read_page(
        self, snapshot: AgUiObservationSnapshot, after_source: int,
    ) -> TaskEventPage | None:
        if not snapshot.bound or snapshot.through < snapshot.run.start:
            return None
        if after_source >= snapshot.through:
            return None
        return self.tasks.read_event_page(
            snapshot.run.task_id, after_source, limit=256, max_bytes=1_048_576,
            through_sequence=snapshot.through,
        )

    def iter_page_frames(
        self,
        snapshot: AgUiObservationSnapshot,
        page: TaskEventPage,
        identity: AgUiRunIdentity,
        *,
        after: AgUiCursor | None = None,
    ) -> Iterator[tuple[AgUiCursor, Event]]:
        if page.highwater != snapshot.through or page.after_sequence < snapshot.run.start - 1:
            raise AgUiProjectionError("observation Page does not match its Run window")
        for entry in page.events:
            header = self.tasks.read_event_projection_header(
                snapshot.head.scope, entry.task_sequence,
            )
            if header is None:
                raise CheckpointNotReady("observation Page is missing a frame header")
            if (
                entry.task_id != snapshot.run.task_id
                or (
                    header.task_sequence, header.event_id, header.segment_id,
                    header.segment_sequence,
                )
                != (
                    entry.task_sequence, entry.event.event_id, entry.segment_id,
                    entry.segment_sequence,
                )
                or entry.event.session_id != entry.segment_id
                or entry.event.sequence != entry.segment_sequence
            ):
                raise CheckpointConflict(
                    "observation Page conflicts with its canonical frame header"
                )
            if not header.eligible:
                continue  # Silent/ineligible source positions still advance the caller's watermark.
            if after is not None and entry.task_sequence < after.sequence:
                continue
            yield from self.materializer.iter_event_frames(
                snapshot.head.scope, entry, identity, run=snapshot.run,
                after=(
                    after if after is not None and entry.task_sequence == after.sequence else None
                ),
            )
