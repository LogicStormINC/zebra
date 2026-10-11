"""Indexed validation of direct rooted certificates; no ancestor walk."""

import json
from uuid import UUID

from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId
from agent_core.ports.agent_tasks import AgentTaskPort
from agent_core.ports.task_projection_checkpoints import (
    MAX_CHECKPOINT_BYTES,
    MAX_CHECKPOINT_KEYS,
    CheckpointConflict,
    ProjectionCell,
    ProjectionCellKey,
    ProjectionScope,
)
from agent_core.ports.task_replay import TaskRunHeader

from agent_integrations.ag_ui.binding_resolution import (
    BINDING_PROOF_KEY,
    binding_scope,
    binding_through,
    checked_handoff,
    member_key,
    validate_binding_scope,
)
from agent_integrations.ag_ui.checkpoint_plan import ProjectionHandoffProof


class BindingCertificateReader:
    """One captured ledger frontier; <=1024 requested keys, never all cells."""

    def __init__(self, tasks: AgentTaskPort, run: TaskRunHeader, scope: ProjectionScope) -> None:
        validate_binding_scope(run, scope)
        self.tasks, self.run, self.scope = tasks, run, binding_scope(scope)
        head = tasks.read_checkpoint_head(self.scope)
        if head.scope != self.scope:
            raise CheckpointConflict("binding head belongs to another scope")
        self.before = min(binding_through(run), head.through_sequence) + 1
        self.cells: dict[SessionId, tuple[ProjectionCell, ...]] = {}

    def rows(self, segment: SessionId) -> tuple[ProjectionCell, ...]:
        self.prefetch((segment,))
        return self.cells[segment]

    def prefetch(self, segments: tuple[SessionId, ...]) -> None:
        missing = tuple(dict.fromkeys(segment for segment in segments if segment not in self.cells))
        if not missing:
            return
        if 2 * (len(self.cells) + len(missing)) > MAX_CHECKPOINT_KEYS:
            raise CheckpointConflict("binding certificate keys exceed the Page bound")
        keys = tuple(
            key
            for segment in missing
            for key in (
                member_key(segment),
                ProjectionCellKey(segment, "handoff", BINDING_PROOF_KEY),
            )
        )
        rows = self.tasks.read_cells_at(self.scope, self.before, keys)
        wanted = set(keys)
        if (
            len(rows) > len(keys)
            or len({row.key for row in rows}) != len(rows)
            or any(
                row.key not in wanted or not self.run.start <= row.task_sequence < self.before
                for row in rows
            )
        ):
            raise CheckpointConflict("binding cells conflict with their frozen frontier")
        grouped: dict[SessionId, list[ProjectionCell]] = {segment: [] for segment in missing}
        for row in rows:
            grouped[row.key.segment_id].append(row)
        self.cells.update((segment, tuple(values)) for segment, values in grouped.items())
        if (
            sum(
                256 + 6 * len(row.key.key.encode()) + 6 * len((row.value or "").encode())
                for values in self.cells.values()
                for row in values
            )
            > MAX_CHECKPOINT_BYTES
        ):
            raise CheckpointConflict("binding certificate cache exceeds its byte bound")

    def prefetch_parents(self, segments: tuple[SessionId, ...]) -> None:
        parents = []
        for segment in segments:
            position = self.member(segment, self.before)
            if position is None or (
                self.run.anchor is not None and segment == self.run.anchor.segment_id
            ):
                continue
            row = next((row for row in self.rows(segment) if row.key.kind == "handoff"), None)
            if row is None or row.task_sequence != position:
                raise CheckpointConflict("binding certificate is missing from its admission")
            parents.append(_decode(row.value, self.run, position)[1])
        self.prefetch(tuple(parents))

    def member(self, segment: SessionId, before: int) -> int | None:
        if before <= self.run.start:
            return None
        if self.run.anchor is not None and segment == self.run.anchor.segment_id:
            return self.run.start
        if self.before <= self.run.start:
            return None
        row = next((row for row in self.rows(segment) if row.key.kind == "run_member"), None)
        if row is not None and row.value != "1":
            raise CheckpointConflict("binding member is not a positive certificate")
        return row.task_sequence if row is not None and row.task_sequence < before else None

    def certificate(self, segment: SessionId, before: int) -> ProjectionHandoffProof | None:
        position = self.member(segment, before)
        if position is None:
            return None
        row = next((row for row in self.rows(segment) if row.key.kind == "handoff"), None)
        if row is None or row.task_sequence != position:
            raise CheckpointConflict("binding certificate is missing from its admission")
        handoff_id, parent_id, commit_position = _decode(row.value, self.run, position)
        receives = self.tasks.read_handoff_receives(
            self.run.task_id,
            segment,
            position - 1,
            through_sequence=position,
            limit=1,
        )
        if len(receives) != 1:
            raise CheckpointConflict("binding certificate receive is missing or ambiguous")
        receive = receives[0]
        checked_handoff(
            receive,
            self.run,
            segment,
            EventType.SESSION_HANDOFF_RECEIVED,
            position - 1,
            position + 1,
        )
        commit = self.tasks.read_latest_handoff_commit(
            self.run.task_id,
            parent_id,
            handoff_id,
            position,
            through_sequence=position,
        )
        if commit is None:
            raise CheckpointConflict("binding certificate commit is missing")
        checked_handoff(
            commit, self.run, parent_id, EventType.SESSION_HANDOFF_COMMITTED, -1, position
        )
        if (
            commit.source.task_sequence != commit_position
            or commit.peer_segment_id != segment
            or commit.handoff_id != handoff_id
            or receive.handoff_id != handoff_id
            or receive.peer_segment_id != parent_id
            or self.member(parent_id, commit_position) is None
        ):
            raise CheckpointConflict("binding certificate conflicts with latest causal source")
        proof = ProjectionHandoffProof(handoff_id, commit.source, receive.source)
        proof.validate(self.run)
        return proof


def _decode(
    value_text: str | None, run: TaskRunHeader, position: int
) -> tuple[UUID, SessionId, int]:
    try:
        value = json.loads(value_text or "")
        if not isinstance(value, list) or len(value) != 3:
            raise ValueError("invalid certificate shape")
        handoff, parent, commit_position = value
        if type(commit_position) is not int or not run.start <= commit_position < position:
            raise ValueError("invalid certificate commit position")
        handoff_id, parent_id = UUID(handoff), SessionId(UUID(parent))
    except (ValueError, TypeError, AttributeError) as exc:
        raise CheckpointConflict("binding certificate is malformed") from exc
    return handoff_id, parent_id, commit_position
