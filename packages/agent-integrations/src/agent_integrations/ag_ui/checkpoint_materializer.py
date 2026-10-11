"""Prepare bounded checkpoint transitions; caller owns the atomic commit.

Only requested cells and this Page's changes are held in memory. Projection
frames are checked and discarded per Event, not retained in a page/history
buffer. This same pure preparation path can run outside SSE during backfill.
"""

from collections.abc import Iterator
from uuid import UUID

from ag_ui.core import Event, RunErrorEvent, RunFinishedEvent
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId
from agent_core.ports.agent_tasks import TaskEvent, TaskEventPage
from agent_core.ports.task_projection_checkpoints import (
    MAX_CHECKPOINT_BYTES,
    MAX_CHECKPOINT_KEYS,
    MAX_EVENT_FRAMES,
    CheckpointConflict,
    CheckpointNotReady,
    CheckpointStale,
    ProjectionCell,
    ProjectionCellKey,
    ProjectionFrameHeader,
    ProjectionScope,
    ProjectionTransition,
    SegmentCheckpoint,
    TaskProjectionCheckpointPort,
)
from agent_core.ports.task_replay import TaskRunHeader

from agent_integrations.ag_ui.binding_resolution import binding_member_before
from agent_integrations.ag_ui.checkpoint_keys import (
    admit_projection,
    projection_keys,
    settle_interrupt_membership,
)
from agent_integrations.ag_ui.checkpoint_plan import (
    AG_UI_CHECKPOINT_VERSION,
    ProjectionPagePlan,
    validate_restore_run,
)
from agent_integrations.ag_ui.contracts import AgUiCursor, AgUiProjectionError, AgUiRunIdentity
from agent_integrations.ag_ui.payload_validation import required_payload_text
from agent_integrations.ag_ui.projection import AgUiProjector
from agent_integrations.ag_ui.projection_state import ProjectionState


class _PageReader:
    def __init__(
        self,
        port: TaskProjectionCheckpointPort,
        scope: ProjectionScope,
        before: int,
    ) -> None:
        self.port, self.scope, self.before = port, scope, before
        self.cells: dict[ProjectionCellKey, ProjectionCell | None] = {}
        self.scalars: dict[SessionId, SegmentCheckpoint] = {}
        self.changes: list[ProjectionCell] = []

    def _check_buffer(self) -> None:
        size = (
            512
            + len(self.scalars) * 128
            + sum(
                256
                + 6 * len(key.key.encode())
                + 6 * len((row.value if row is not None and row.value is not None else "").encode())
                for key, row in self.cells.items()
            )
            + sum(
                256 + 6 * len(row.key.key.encode()) + 6 * len((row.value or "").encode())
                for row in self.changes
            )
        )
        if size > MAX_CHECKPOINT_BYTES:
            raise AgUiProjectionError("checkpoint Page buffer exceeds byte bound")

    def load(self, keys: tuple[ProjectionCellKey, ...]) -> tuple[ProjectionCell, ...]:
        missing = tuple(dict.fromkeys(key for key in keys if key not in self.cells))
        if len(self.cells) + len(missing) > MAX_CHECKPOINT_KEYS:
            raise AgUiProjectionError("checkpoint Page exceeds keyed-state bound")
        if missing:
            rows = self.port.read_cells_at(self.scope, self.before, missing)
            if len(rows) > len(missing):
                raise CheckpointConflict("checkpoint returned excess keyed rows")
            found: set[ProjectionCellKey] = set()
            size = 0
            for row in rows:
                if row.key not in missing or row.key in found or row.task_sequence >= self.before:
                    raise CheckpointConflict("checkpoint returned foreign/future cell")
                found.add(row.key)
                size += 128 + len(row.key.key.encode()) + len((row.value or "").encode())
                self.cells[row.key] = row
            if size > MAX_CHECKPOINT_BYTES:
                raise AgUiProjectionError("checkpoint cell read exceeds byte bound")
            self.cells.update((key, None) for key in missing if key not in found)
            self._check_buffer()
        return tuple(cached for key in keys if (cached := self.cells[key]) is not None)

    def scalar(self, segment: SessionId) -> SegmentCheckpoint:
        if segment not in self.scalars:
            scalar = self.port.read_segment_checkpoint_before(self.scope, segment, self.before)
            if scalar.segment_id != segment or scalar.task_sequence >= self.before:
                raise CheckpointConflict("checkpoint returned foreign/future scalar")
            self.scalars[segment] = scalar
        return self.scalars[segment]

    def change(self, key: ProjectionCellKey, position: int, value: str | None) -> None:
        rows = self.load((key,))
        if (rows[0].value if rows else None) == value:
            return
        if len(self.changes) >= MAX_CHECKPOINT_KEYS:
            raise AgUiProjectionError("checkpoint Page exceeds cell-transition bound")
        row = ProjectionCell(key, position, value)
        self.cells[key] = row
        self.changes.append(row)
        self._check_buffer()


def _segment_identity(identity: AgUiRunIdentity, segment: SessionId) -> AgUiRunIdentity:
    # Task projector historically does not propagate a parent_run_id to Segments.
    return AgUiRunIdentity(session_id=segment, thread_id=identity.thread_id, run_id=identity.run_id)


def _state_for(
    reader: _PageReader,
    entry: TaskEvent,
    identity: AgUiRunIdentity,
) -> tuple[ProjectionState, tuple[ProjectionCellKey, ...], SegmentCheckpoint]:
    scalar = reader.scalar(entry.segment_id)
    keys = projection_keys(entry.event)
    cells = reader.load(keys)
    message = next((c.value for c in cells if c.key.kind == "text_message"), None)
    if message is not None:
        keys = projection_keys(entry.event, message_id=message)
        cells = reader.load(keys)
    if any(cell.task_sequence > scalar.task_sequence for cell in cells):
        raise CheckpointConflict("projector cell is newer than its Segment scalar")
    return ProjectionState.from_checkpoint(scalar, cells, identity), keys, scalar


def _check_frames(frames: tuple[Event, ...]) -> None:
    if len(frames) > MAX_EVENT_FRAMES:
        raise AgUiProjectionError("durable Event exceeds frame-count bound")
    size = 0
    for frame in frames:
        size += len(frame.model_dump_json(by_alias=True, exclude_none=True).encode())
        if size > MAX_CHECKPOINT_BYTES:
            raise AgUiProjectionError("durable Event exceeds projected-frame byte bound")


def _member_key(segment: SessionId) -> ProjectionCellKey:
    return ProjectionCellKey(segment, "run_member", "member")


def _prepare_membership(reader: _PageReader, page: TaskEventPage, plan: ProjectionPagePlan) -> None:
    run = plan.run
    if run.legacy or run.control_only or run.anchor is None:
        return
    root = run.anchor.segment_id
    lookahead: dict[SessionId, int] = {}

    def admitted(segment: SessionId, position: int, *, future: bool = False) -> bool:
        if segment == root:
            return True
        rows = reader.load((_member_key(segment),))
        if rows and rows[0].value == "1" and rows[0].task_sequence < position:
            return True
        if binding_member_before(reader.port, run, reader.scope, segment, position) is not None:
            return True
        return segment in lookahead and (future or lookahead[segment] < position)

    for proof in sorted(plan.handoffs, key=lambda p: p.commit.task_sequence):
        if not admitted(proof.commit.segment_id, proof.commit.task_sequence):
            raise CheckpointConflict("handoff lookahead source was not yet admitted")
        segment = proof.receive.segment_id
        lookahead[segment] = min(
            lookahead.get(segment, proof.receive.task_sequence), proof.receive.task_sequence
        )
        for entry in page.events:
            if entry.task_sequence not in {proof.commit.task_sequence, proof.receive.task_sequence}:
                continue
            expected = (
                proof.commit if entry.task_sequence == proof.commit.task_sequence else proof.receive
            )
            payload = entry.event.payload
            peer = proof.receive.segment_id if expected is proof.commit else proof.commit.segment_id
            field = "target_session_id" if expected is proof.commit else "parent_session_id"
            if (
                entry.event.event_id != expected.event_id
                or entry.segment_id != expected.segment_id
                or entry.segment_sequence != expected.segment_sequence
                or entry.event.event_type != expected.event_type
                or UUID(required_payload_text(payload, "handoff_id")) != proof.handoff_id
                or UUID(required_payload_text(payload, field)) != peer
            ):
                raise CheckpointConflict("handoff lookahead conflicts with canonical Page payload")
    for entry, decision in zip(page.events, plan.events, strict=True):
        position = entry.task_sequence
        if position == run.start:
            reader.change(_member_key(root), position, "1")
        if position < run.start or (run.stop is not None and position >= run.stop):
            continue
        skipped = ProjectionCellKey(entry.segment_id, "run_member", "unprojected")
        if decision.projected and any(row.value == "1" for row in reader.load((skipped,))):
            raise CheckpointConflict("late handoff would retroactively warm published Events")
        if not decision.projected:
            reader.change(skipped, position, "1")
        payload = entry.event.payload
        if entry.event.event_type is EventType.SESSION_HANDOFF_COMMITTED and admitted(
            entry.segment_id, position
        ):
            handoff = str(UUID(required_payload_text(payload, "handoff_id")))
            target = str(UUID(required_payload_text(payload, "target_session_id")))
            if any(
                proof.handoff_id == UUID(handoff)
                and proof.commit.segment_id == entry.segment_id
                and proof.commit.task_sequence < position < proof.receive.task_sequence
                for proof in plan.handoffs
            ):
                raise CheckpointConflict("handoff lookahead was superseded before its receive")
            reader.change(ProjectionCellKey(entry.segment_id, "handoff", handoff), position, target)
        elif entry.event.event_type is EventType.SESSION_HANDOFF_RECEIVED:
            handoff = str(UUID(required_payload_text(payload, "handoff_id")))
            parent = SessionId(UUID(required_payload_text(payload, "parent_session_id")))
            rows = reader.load((ProjectionCellKey(parent, "handoff", handoff),))
            if any(
                proof.receive.task_sequence == position
                and (
                    not rows
                    or rows[0].task_sequence != proof.commit.task_sequence
                    or rows[0].value != str(entry.segment_id)
                )
                for proof in plan.handoffs
            ):
                raise CheckpointConflict(
                    "handoff lookahead does not match the latest causal commit"
                )
            if rows and rows[0].task_sequence < position and rows[0].value == str(entry.segment_id):
                skipped_rows = reader.load((skipped,))
                if skipped_rows and skipped_rows[0].value == "1":
                    raise CheckpointConflict(
                        "late handoff would retroactively warm published Events"
                    )
                reader.change(_member_key(entry.segment_id), position, "1")
    for entry, decision in zip(page.events, plan.events, strict=True):
        if decision.eligible and entry.segment_id != root:
            if not admitted(entry.segment_id, page.next_sequence + 1, future=True):
                raise CheckpointNotReady("bound Segment has no resolved paired handoff")


class AgUiCheckpointMaterializer:
    def __init__(
        self,
        port: TaskProjectionCheckpointPort,
        projector: AgUiProjector | None = None,
    ) -> None:
        self.port = port
        self.projector = projector or AgUiProjector()

    def prepare_page(
        self,
        page: TaskEventPage,
        plan: ProjectionPagePlan,
        scope: ProjectionScope,
        identity: AgUiRunIdentity,
    ) -> ProjectionTransition | None:
        """No writes: return one validated CAS transition, or None for an empty Page."""
        plan.validate(page, scope, identity)
        head = self.port.read_checkpoint_head(scope)
        if head.scope != scope or head.through_sequence < page.after_sequence:
            raise CheckpointConflict("checkpoint Page does not extend its exact frontier")
        if head.through_sequence > page.after_sequence:
            raise CheckpointStale("checkpoint frontier advanced before preparation")
        if not page.events:
            return None
        reader = _PageReader(self.port, scope, page.after_sequence + 1)
        _prepare_membership(reader, page, plan)
        headers: list[ProjectionFrameHeader] = []
        scalars: list[SegmentCheckpoint] = []
        terminal: int | None = None
        for entry, decision in zip(page.events, plan.events, strict=True):
            previous = -1
            frames: tuple[Event, ...] = ()
            if decision.projected:
                segment_identity = _segment_identity(identity, entry.segment_id)
                state, keys, scalar = _state_for(reader, entry, segment_identity)
                previous = scalar.task_sequence
                admit_projection(entry.event, segment_identity, started=state.started)
                _, frames = next(
                    self.projector.project_events(
                        (entry.event,),
                        segment_identity,
                        state=state,
                    )
                )
                _check_frames(frames)
                settle_interrupt_membership(entry.event, state)
                for key in keys:
                    reader.change(key, entry.task_sequence, state.checkpoint_value(key))
                scalar = SegmentCheckpoint(
                    entry.segment_id,
                    entry.task_sequence,
                    entry.segment_sequence,
                    state.started,
                    state.turn_finished,
                )
                scalars.append(scalar)
                reader.scalars[entry.segment_id] = scalar
                if decision.eligible and any(
                    isinstance(f, RunFinishedEvent | RunErrorEvent) for f in frames
                ):
                    terminal = entry.task_sequence
            headers.append(
                ProjectionFrameHeader(
                    entry.task_sequence,
                    entry.event.event_id,
                    entry.segment_id,
                    entry.segment_sequence,
                    previous,
                    len(frames),
                    decision.projected,
                    decision.eligible,
                )
            )
        return ProjectionTransition(
            scope,
            page.after_sequence,
            tuple(headers),
            tuple(scalars),
            tuple(reader.changes),
            terminal,
        )

    def _restore_header(
        self,
        scope: ProjectionScope,
        entry: TaskEvent,
        identity: AgUiRunIdentity,
        *,
        run: TaskRunHeader,
    ) -> ProjectionFrameHeader:
        """Validate even whole-Event cursors before skipping their public frames."""
        if scope.projector_version != AG_UI_CHECKPOINT_VERSION:
            raise AgUiProjectionError("unsupported checkpoint projector version")
        if entry.task_id != scope.task_id or str(scope.task_id) != identity.thread_id:
            raise AgUiProjectionError("checkpoint belongs to another Task")
        validate_restore_run(scope, run, identity, entry.task_sequence)
        head = self.port.read_checkpoint_head(scope)
        if head.scope != scope or entry.task_sequence > head.through_sequence:
            raise CheckpointNotReady("anchor checkpoint is not ready")
        header = self.port.read_event_projection_header(scope, entry.task_sequence)
        if header is None:
            raise CheckpointNotReady("anchor frame header is not ready")
        if (
            (header.event_id, header.segment_id, header.segment_sequence, header.task_sequence)
            != (
                entry.event.event_id,
                entry.segment_id,
                entry.segment_sequence,
                entry.task_sequence,
            )
            or entry.segment_id != entry.event.session_id
            or entry.segment_sequence != entry.event.sequence
        ):
            raise CheckpointConflict("frame header conflicts with canonical Event")
        if not header.eligible:
            raise AgUiProjectionError("anchor frame is outside the bound run")
        return header

    def restore_event_frames(
        self,
        scope: ProjectionScope,
        entry: TaskEvent,
        identity: AgUiRunIdentity,
        *,
        run: TaskRunHeader,
    ) -> tuple[Event, ...]:
        """Restore strictly before one exact anchor and project its body once."""
        header = self._restore_header(scope, entry, identity, run=run)
        reader = _PageReader(self.port, scope, entry.task_sequence)
        segment_identity = _segment_identity(identity, entry.segment_id)
        state, _, scalar = _state_for(reader, entry, segment_identity)
        if scalar.task_sequence != header.state_before_sequence:
            raise CheckpointConflict("frame header references another predecessor checkpoint")
        admit_projection(entry.event, segment_identity, started=state.started)
        _, frames = next(
            self.projector.project_events((entry.event,), segment_identity, state=state)
        )
        _check_frames(frames)
        if len(frames) != header.frame_count:
            raise CheckpointConflict("anchor frame count conflicts with checkpoint version")
        return frames

    def iter_event_frames(
        self,
        scope: ProjectionScope,
        entry: TaskEvent,
        identity: AgUiRunIdentity,
        *,
        run: TaskRunHeader,
        after: AgUiCursor | None = None,
    ) -> Iterator[tuple[AgUiCursor, Event]]:
        validate_restore_run(scope, run, identity, entry.task_sequence)
        if after is not None and (
            after.thread_id != identity.thread_id
            or after.run_id != identity.run_id
            or after.sequence != entry.task_sequence
            or after.event_id != str(entry.event.event_id)
        ):
            raise AgUiProjectionError("cursor does not identify the exact anchor")
        if after is not None and after.frame_index is None:
            self._restore_header(scope, entry, identity, run=run)
            return
        frames = self.restore_event_frames(scope, entry, identity, run=run)
        if after is not None and after.frame_index is not None and after.frame_index >= len(frames):
            raise AgUiProjectionError("cursor frame is outside its durable Event")
        start = after.frame_index + 1 if after is not None and after.frame_index is not None else 0
        for index in range(start, len(frames)):
            yield (
                AgUiCursor(
                    thread_id=identity.thread_id,
                    run_id=identity.run_id,
                    sequence=entry.task_sequence,
                    event_id=str(entry.event.event_id),
                    frame_index=index,
                ),
                frames[index],
            )
