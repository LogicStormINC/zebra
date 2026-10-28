"""Indexed binding for one frozen, bounded Page; no historical payload reads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId
from agent_core.ports.agent_tasks import AgentTaskPort, TaskEventPage
from agent_core.ports.task_projection_checkpoints import (
    MAX_CHECKPOINT_EVENTS,
    MAX_CHECKPOINT_KEYS,
    CheckpointConflict,
    ProjectionCellKey,
    ProjectionScope,
)
from agent_core.ports.task_replay import TaskEventHeader, TaskHandoffHeader, TaskRunHeader

from agent_integrations.ag_ui.binding_certificates import BindingCertificateReader
from agent_integrations.ag_ui.binding_resolution import BindingResolutionPending
from agent_integrations.ag_ui.checkpoint_plan import (
    ProjectionEventPlan,
    ProjectionHandoffProof,
    ProjectionPagePlan,
    checkpoint_version,
)
from agent_integrations.ag_ui.contracts import AgUiProjectionError, AgUiRunIdentity
from agent_integrations.ag_ui.profiles import AgUiProjectionProfile


@dataclass(frozen=True, slots=True)
class _Admission:
    position: int
    proof: ProjectionHandoffProof | None = None
    parent: _Admission | None = None


class _Resolver:
    def __init__(
        self,
        tasks: AgentTaskPort,
        scope: ProjectionScope,
        run: TaskRunHeader,
        before: int,
        segments: tuple[SessionId, ...],
    ) -> None:
        self.tasks, self.scope, self.run, self.before = tasks, scope, run, before
        self.through = min(run.highwater, run.stop - 1 if run.stop is not None else run.highwater)
        self.cached: dict[SessionId, _Admission | None] = {}
        self.resolved: dict[tuple[SessionId, int], _Admission | None] = {}
        self.queries = self.receives = 0
        self.ledger = (
            BindingCertificateReader(tasks, run, scope)
            if run.anchor is not None and not run.legacy and not run.control_only
            else None
        )
        if self.ledger is not None and self.ledger.before > run.start:
            self.ledger.prefetch(segments)
            self.ledger.prefetch_parents(segments)

    def spend(self, count: int = 1) -> None:
        self.queries += count
        if self.queries > MAX_CHECKPOINT_KEYS:
            raise self.pending("binding metadata query budget exhausted", "budget")

    def pending(
        self,
        message: str,
        reason: Literal["budget", "resolution", "admission"],
    ) -> BindingResolutionPending:
        return BindingResolutionPending(
            message,
            reason=reason,
            resolved_through=self.ledger.before - 1 if self.ledger is not None else -1,
            required_through=self.through,
        )

    def prior(self, segment: SessionId) -> _Admission | None:
        if segment not in self.cached:
            self.spend()
            key = ProjectionCellKey(segment, "run_member", "member")
            rows = self.tasks.read_cells_at(self.scope, self.before, (key,))
            if len(rows) > 1 or any(
                row.key != key or row.task_sequence >= self.before for row in rows
            ):
                raise CheckpointConflict("binding received foreign/future membership state")
            row = rows[0] if rows else None
            if row is not None and row.task_sequence < self.run.start:
                raise CheckpointConflict("binding membership precedes its Run")
            self.cached[segment] = (
                _Admission(row.task_sequence) if row is not None and row.value == "1" else None
            )
        return self.cached[segment]

    def source(
        self,
        header: TaskHandoffHeader,
        segment: SessionId,
        kind: EventType,
        after: int,
        before: int,
    ) -> None:
        source = header.source
        if (
            source.task_id != self.run.task_id
            or source.segment_id != segment
            or source.event_type is not kind
            or not after < source.task_sequence < before
            or source.task_sequence > self.through
        ):
            raise CheckpointConflict("binding handoff conflicts with frozen source window")

    def admission(self, segment: SessionId, before: int, depth: int = 0) -> _Admission | None:
        if before <= self.run.start:
            return None
        if self.run.anchor is not None and segment == self.run.anchor.segment_id:
            return _Admission(self.run.start)
        key = segment, before
        if key in self.resolved:
            return self.resolved[key]
        self.spend(2)
        proof = self.ledger.certificate(segment, before) if self.ledger is not None else None
        if proof is not None:
            result = _Admission(proof.receive.task_sequence, proof)
            self.resolved[key] = result
            return result
        prior = self.prior(segment)
        if prior is not None and prior.position < before:
            self.resolved[key] = prior
            return prior
        if self.ledger is not None and self.ledger.before > self.run.start:
            if self.ledger.before < min(self.through + 1, before):
                raise self.pending("binding ledger requires bounded continuation", "resolution")
            self.resolved[key] = None
            return None  # Durable absence at H is final only when the Run closes.
        if depth >= MAX_CHECKPOINT_EVENTS:
            raise self.pending("binding causal depth budget exhausted", "budget")
        after, through = self.run.start - 1, min(self.through, before - 1)
        while after < through:
            self.spend()
            # One overflow sentinel distinguishes exhausted budget from no receive.
            limit = min(MAX_CHECKPOINT_EVENTS, MAX_CHECKPOINT_EVENTS - self.receives + 1)
            rows = self.tasks.read_handoff_receives(
                self.run.task_id,
                segment,
                after,
                through_sequence=through,
                limit=limit,
            )
            if len(rows) > limit:
                raise CheckpointConflict("binding returned excess handoff rows")
            self.receives += len(rows)
            if self.receives > MAX_CHECKPOINT_EVENTS:
                raise self.pending("binding handoff row budget exhausted", "budget")
            for receive in rows:
                self.source(receive, segment, EventType.SESSION_HANDOFF_RECEIVED, after, before)
                after = receive.source.task_sequence
                self.spend()
                commit = self.tasks.read_latest_handoff_commit(
                    self.run.task_id,
                    receive.peer_segment_id,
                    receive.handoff_id,
                    after,
                    through_sequence=self.through,
                )
                if commit is None:
                    continue  # An orphan is a fact, not a request to hydrate/repair.
                self.source(
                    commit,
                    receive.peer_segment_id,
                    EventType.SESSION_HANDOFF_COMMITTED,
                    -1,
                    after,
                )
                if commit.handoff_id != receive.handoff_id:
                    raise CheckpointConflict("binding returned another handoff identity")
                if (
                    commit.source.task_sequence < self.run.start
                    or commit.peer_segment_id != segment
                ):
                    continue  # Latest conflicting commit supersedes older matching ones.
                parent = self.admission(
                    commit.source.segment_id,
                    commit.source.task_sequence,
                    depth + 1,
                )
                if parent is not None:
                    result = _Admission(
                        after,
                        ProjectionHandoffProof(receive.handoff_id, commit.source, receive.source),
                        parent,
                    )
                    self.resolved[key] = result
                    return result
            if len(rows) < limit:
                break
        self.resolved[key] = None
        return None


def _closed_window(tasks: AgentTaskPort, run: TaskRunHeader, closed_through: int | None) -> bool:
    if closed_through is None:
        return run.stop is not None
    if (
        type(closed_through) is not int
        or closed_through != run.highwater
        or closed_through < run.start
        or run.anchor is None
        or run.legacy
        or run.control_only
    ):
        raise CheckpointConflict("binding closure conflicts with its frozen Run")
    # Queue seals H at next-anchor-1. Verify that one indexed header, not a caller bool.
    confirmed = tasks.read_run_header(run.task_id, run.run_id, through_sequence=closed_through + 1)
    if (
        confirmed.task_id != run.task_id
        or confirmed.run_id != run.run_id
        or confirmed.anchor != run.anchor
        or confirmed.start != run.start
        or confirmed.highwater != closed_through + 1
        or confirmed.stop != closed_through + 1
        or confirmed.legacy
        or confirmed.control_only
    ):
        raise CheckpointConflict("binding closure lacks a canonical next Run anchor")
    return True


def build_projection_page_plan(
    tasks: AgentTaskPort,
    page: TaskEventPage,
    run: TaskRunHeader,
    scope: ProjectionScope,
    identity: AgUiRunIdentity,
    *,
    closed_through: int | None = None,
    profile: AgUiProjectionProfile | None = None,
) -> ProjectionPagePlan:
    """Warm the whole selected block, including its pre-anchor prefix.

    Durable rooted certificates cut deep walks; short cold lookahead remains
    bounded and read-only. Budget exhaustion requests explicit background
    advance_binding_resolution, never a query-time write or history hydration.
    Absence in an open Run cannot publish a permanent negative header: a later
    causal receive may select this whole prefix under the original replay oracle.
    """
    anchor = run.anchor.event_id if run.anchor is not None else None
    if (
        scope.projector_version != checkpoint_version(run, profile)
        or scope.task_id != run.task_id
        or str(run.task_id) != identity.thread_id
        or run.run_id != identity.run_id
        or scope.anchor_event_id != anchor
        or page.highwater != run.highwater
        or any(entry.task_id != run.task_id for entry in page.events)
    ):
        raise AgUiProjectionError("binding Page belongs to another Task/run/snapshot")
    closed = _closed_window(tasks, run, closed_through)
    resolver = _Resolver(
        tasks,
        scope,
        run,
        page.after_sequence + 1,
        tuple(dict.fromkeys(entry.segment_id for entry in page.events)),
    )
    plans: list[ProjectionEventPlan] = []
    proofs: dict[tuple[int, int], ProjectionHandoffProof] = {}
    block = None
    selected, end = False, -1
    for entry in page.events:
        source = TaskEventHeader(
            entry.task_id,
            entry.task_sequence,
            entry.event.event_id,
            entry.segment_id,
            entry.segment_sequence,
            entry.event.event_type,
        )
        projected = run.legacy and not run.control_only
        if not run.legacy and not run.control_only and run.anchor is not None:
            if block is None or entry.task_sequence > block.last_task_sequence:
                resolver.spend()
                block = tasks.read_projection_block(
                    run.task_id,
                    entry.task_sequence,
                    through_sequence=run.highwater,
                )
                if (
                    block.task_id != run.task_id
                    or block.segment_id != entry.segment_id
                    or not block.first_task_sequence
                    <= entry.task_sequence
                    <= block.last_task_sequence
                    or block.last_task_sequence > run.highwater
                ):
                    raise CheckpointConflict("binding block conflicts with canonical Page")
                end = min(block.last_task_sequence, resolver.through)
                selected = False
                if max(block.first_task_sequence, run.start) <= end:
                    admission = resolver.admission(entry.segment_id, resolver.through + 1)
                    selected = admission is not None
                    if not selected and not closed:
                        raise resolver.pending(
                            "block awaits causal admission or Run closure", "admission"
                        )
                    while admission is not None and admission.proof is not None:
                        proof = admission.proof
                        proofs[proof.commit.task_sequence, proof.receive.task_sequence] = proof
                        admission = admission.parent
            if block.segment_id != entry.segment_id or (
                entry.segment_sequence
                != block.first_segment_sequence + entry.task_sequence - block.first_task_sequence
            ):
                raise CheckpointConflict("binding block has foreign/noncontiguous source")
            projected = selected and entry.task_sequence <= end
        plans.append(
            ProjectionEventPlan(source, projected, projected and entry.task_sequence >= run.start)
        )
    plan = ProjectionPagePlan(run, tuple(plans), tuple(proofs.values()))
    plan.validate(page, scope, identity, profile)
    return plan
