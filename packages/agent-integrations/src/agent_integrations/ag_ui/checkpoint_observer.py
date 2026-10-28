"""Read-only, bounded observation of a shared durable AG-UI projection."""

from collections.abc import Iterator
from contextlib import nullcontext
from dataclasses import dataclass

from ag_ui.core import Event
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import TaskId
from agent_core.ports.agent_tasks import AgentTaskPort, TaskEventPage
from agent_core.ports.stream_source_head import StreamObservationReadPort, StreamSourceHeadPort
from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    CheckpointNotReady,
    ProjectionCheckpointHead,
    ProjectionScope,
)
from agent_core.ports.task_replay import TaskRunHeader

from agent_integrations.ag_ui.checkpoint_materializer import AgUiCheckpointMaterializer
from agent_integrations.ag_ui.checkpoint_plan import (
    AG_UI_CHECKPOINT_VERSION,
    AG_UI_COVERAGE_CHECKPOINT_VERSION,
    checkpoint_version,
)
from agent_integrations.ag_ui.contracts import AgUiCursor, AgUiProjectionError, AgUiRunIdentity
from agent_integrations.ag_ui.profiles import AgUiProjectionProfile


@dataclass(frozen=True, slots=True)
class AgUiObservationSnapshot:
    run: TaskRunHeader
    head: ProjectionCheckpointHead
    command_outcome: str | None = None
    outcome_checked: bool = False

    @property
    def bound(self) -> bool:
        return not self.run.control_only and (self.run.legacy or self.run.anchor is not None)

    @property
    def through(self) -> int:
        stop = self.run.stop - 1 if self.run.stop is not None else self.run.highwater
        return min(stop, self.head.through_sequence, self.run.highwater)


class AgUiCheckpointObserver:
    """Never hydrates a Task, materializes checkpoints, or executes commands."""

    def __init__(
        self,
        tasks: AgentTaskPort,
        *,
        namespace: str,
        initial_metadata: StreamObservationReadPort | None = None,
        profile: AgUiProjectionProfile | None = None,
    ) -> None:
        self.tasks, self.namespace = tasks, namespace
        self.initial_metadata = initial_metadata
        self.profile = profile
        self.materializer = AgUiCheckpointMaterializer(tasks, profile=profile)

    def snapshot(
        self,
        task_id: TaskId,
        identity: AgUiRunIdentity,
        host_context: HostContextEnvelope | None = None,
    ) -> AgUiObservationSnapshot:
        if str(task_id) != identity.thread_id:
            raise AgUiProjectionError("observation belongs to another Task")
        read_head = None
        if self.initial_metadata is not None:
            read_head = self.initial_metadata.read_stream_checkpoint_head
        elif isinstance(self.tasks, StreamSourceHeadPort) and getattr(
            self.tasks, "stream_head_reads_compatible", True
        ):
            read_head = self.tasks.read_stream_checkpoint_head
        if read_head is not None:
            captured = read_head(
                task_id,
                identity.run_id,
                ordinary_version=(
                    self.profile.checkpoint_version() if self.profile else AG_UI_CHECKPOINT_VERSION
                ),
                coverage_version=(
                    self.profile.checkpoint_version(coverage=True)
                    if self.profile
                    else AG_UI_COVERAGE_CHECKPOINT_VERSION
                ),
                host_context=host_context,
            )
            run, head = captured.run, captured.head
            if run.task_id != task_id or run.run_id != identity.run_id:
                raise CheckpointConflict("observation Run belongs to another Task/run")
            if self.profile is not None:
                self.profile.binding_digest(head.scope, run)
            return AgUiObservationSnapshot(
                run, head, captured.command_outcome, host_context is not None
            )
        run = self.tasks.read_run_header(task_id, identity.run_id)
        if run.task_id != task_id or run.run_id != identity.run_id:
            raise CheckpointConflict("observation Run belongs to another Task/run")
        scope = ProjectionScope(
            self.namespace,
            task_id,
            run.anchor.event_id if run.anchor else None,
            checkpoint_version(run, self.profile),
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
                refreshed.anchor != run.anchor
                or refreshed.start != run.start
                or refreshed.legacy != run.legacy
                or refreshed.control_only != run.control_only
                or refreshed.strict_coverage != run.strict_coverage
            ):
                raise CheckpointNotReady("observation Run changed while capturing its head")
            run = refreshed
        if head.scope != scope or head.through_sequence > run.highwater:
            raise CheckpointConflict("observation head conflicts with captured source coverage")
        if self.profile is not None:
            self.profile.binding_digest(head.scope, run)
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
        digest = self.profile.binding_digest(snapshot.head.scope, run) if self.profile else None
        if cursor.profile_scope != digest:
            raise AgUiProjectionError("cursor belongs to another profile binding")
        if (
            not snapshot.bound
            or cursor.thread_id != identity.thread_id
            or cursor.run_id != identity.run_id
            or not max(0, run.start - 1) <= cursor.sequence <= run.highwater
            or (run.stop is not None and cursor.sequence >= run.stop)
        ):
            raise AgUiProjectionError("cursor is outside the requested Task/run")
        reader = self.initial_metadata if self.initial_metadata is not None else self.tasks
        source = reader.read_event_header(run.task_id, cursor.sequence)
        if source is None or str(source.event_id) != cursor.event_id:
            raise AgUiProjectionError("cursor does not identify a canonical Task Event")
        if source.task_id != run.task_id or source.task_sequence != cursor.sequence:
            raise CheckpointConflict("cursor source locator conflicts with its Task position")
        if cursor.frame_index is None:
            return
        if cursor.sequence < run.start:
            raise AgUiProjectionError("cursor frame precedes its Run")
        header = reader.read_event_projection_header(snapshot.head.scope, cursor.sequence)
        if header is None:
            raise CheckpointNotReady("cursor frame checkpoint is not ready")
        if (header.event_id, header.segment_id, header.segment_sequence) != (
            source.event_id,
            source.segment_id,
            source.segment_sequence,
        ) or header.task_sequence != source.task_sequence:
            raise CheckpointConflict("cursor frame conflicts with canonical source")
        if not header.eligible or cursor.frame_index >= header.frame_count:
            raise AgUiProjectionError("cursor frame is outside its durable Event")

    def recovery_cursor(
        self,
        snapshot: AgUiObservationSnapshot,
        identity: AgUiRunIdentity,
    ) -> AgUiCursor | None:
        header = snapshot.head.latest_eligible
        if (
            not snapshot.bound
            or header is None
            or not snapshot.run.start <= header.task_sequence <= snapshot.through
        ):
            return None
        return AgUiCursor(
            thread_id=identity.thread_id,
            run_id=identity.run_id,
            sequence=header.task_sequence,
            event_id=str(header.event_id),
            frame_index=header.frame_count - 1 if header.frame_count else None,
            version=2 if self.profile else 1,
            profile_scope=(
                self.profile.binding_digest(snapshot.head.scope, snapshot.run)
                if self.profile
                else None
            ),
        )

    def read_page(
        self,
        snapshot: AgUiObservationSnapshot,
        after_source: int,
    ) -> TaskEventPage | None:
        if not snapshot.bound or snapshot.through < snapshot.run.start:
            return None
        if after_source >= snapshot.through:
            return None
        return self.tasks.read_event_page(
            snapshot.run.task_id,
            after_source,
            limit=256,
            max_bytes=1_048_576,
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
            snapshot_read = (
                self.tasks.read_checkpoint_snapshot(snapshot.head.scope, entry.task_sequence)
                if (
                    isinstance(self.tasks, StreamSourceHeadPort)
                    and getattr(self.tasks, "stream_head_reads_compatible", True)
                )
                else nullcontext(self.tasks)
            )
            # The bounded Event restore finishes and releases its socket before yield.
            with snapshot_read as reader:
                header = reader.read_event_projection_header(
                    snapshot.head.scope,
                    entry.task_sequence,
                )
                if header is None:
                    raise CheckpointNotReady("observation Page is missing a frame header")
                if (
                    entry.task_id != snapshot.run.task_id
                    or (
                        header.task_sequence,
                        header.event_id,
                        header.segment_id,
                        header.segment_sequence,
                    )
                    != (
                        entry.task_sequence,
                        entry.event.event_id,
                        entry.segment_id,
                        entry.segment_sequence,
                    )
                    or entry.event.session_id != entry.segment_id
                    or entry.event.sequence != entry.segment_sequence
                ):
                    raise CheckpointConflict(
                        "observation Page conflicts with its canonical frame header"
                    )
                if not header.eligible:
                    # Silent source positions still advance the caller's watermark.
                    continue
                if after is not None and entry.task_sequence < after.sequence:
                    continue
                frames = tuple(
                    AgUiCheckpointMaterializer(
                        reader, self.materializer.projector, profile=self.profile
                    ).iter_event_frames(
                        snapshot.head.scope,
                        entry,
                        identity,
                        run=snapshot.run,
                        after=(
                            after
                            if after is not None and entry.task_sequence == after.sequence
                            else None
                        ),
                    )
                )
            for frame in frames:
                current = self.tasks.read_run_header(snapshot.run.task_id, identity.run_id)
                if (
                    current.task_id != snapshot.run.task_id
                    or current.run_id != identity.run_id
                    or current.anchor != snapshot.run.anchor
                    or current.start != snapshot.run.start
                    or current.strict_coverage != snapshot.run.strict_coverage
                ):
                    raise CheckpointNotReady("observation Run privacy changed before delivery")
                yield frame
