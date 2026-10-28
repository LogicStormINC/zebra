"""Bounded binding decisions supplied by the indexed, body-free binding pass.

The binding pass must resolve paired handoffs before publishing a selected
contiguous block. A later handoff may not retroactively change committed plans.
Warm rows include *all* prefixes of selected blocks, even before the run anchor;
an unselected block must not warm state. No request-time prefix scan is allowed.
"""

from dataclasses import dataclass
from uuid import UUID

from agent_core.domain.events import EventType
from agent_core.ports.agent_tasks import TaskEventPage
from agent_core.ports.task_projection_checkpoints import MAX_CHECKPOINT_EVENTS, ProjectionScope
from agent_core.ports.task_replay import TaskEventHeader, TaskRunHeader

from agent_integrations.ag_ui.contracts import AgUiProjectionError, AgUiRunIdentity
from agent_integrations.ag_ui.profiles import AgUiProjectionProfile
from agent_integrations.coverage_public_events import strict_coverage_events

AG_UI_CHECKPOINT_VERSION = "ag-ui-v1"
AG_UI_COVERAGE_CHECKPOINT_VERSION = "ag-ui-v1-coverage"


def checkpoint_version(run: TaskRunHeader, profile: AgUiProjectionProfile | None = None) -> str:
    if profile is not None:
        return profile.checkpoint_version(coverage=run.strict_coverage)
    return AG_UI_COVERAGE_CHECKPOINT_VERSION if run.strict_coverage else AG_UI_CHECKPOINT_VERSION


@dataclass(frozen=True, slots=True)
class ProjectionEventPlan:
    source: TaskEventHeader
    projected: bool
    eligible: bool

    def __post_init__(self) -> None:
        if type(self.projected) is not bool or type(self.eligible) is not bool:
            raise AgUiProjectionError("invalid projection plan flags")
        if self.eligible and not self.projected:
            raise AgUiProjectionError("eligible Event must be projected")


@dataclass(frozen=True, slots=True)
class ProjectionHandoffProof:
    """An indexed canonical pair, not caller-supplied execution authority.

    The binding adapter verifies payload identities and the latest eligible
    commit before this receive in its frozen metadata index. Lookahead is
    only for selecting/warming an earlier block; it cannot authorize a handoff
    commit before the source Segment's own receive position.
    """

    handoff_id: UUID
    commit: TaskEventHeader
    receive: TaskEventHeader

    def validate(self, run: TaskRunHeader) -> None:
        if (
            not isinstance(self.handoff_id, UUID)
            or self.commit.task_id != run.task_id
            or self.receive.task_id != run.task_id
            or self.commit.event_type is not EventType.SESSION_HANDOFF_COMMITTED
            or self.receive.event_type is not EventType.SESSION_HANDOFF_RECEIVED
            or not run.start
            <= self.commit.task_sequence
            < self.receive.task_sequence
            <= run.highwater
            or (run.stop is not None and self.receive.task_sequence >= run.stop)
            or self.commit.event_id == self.receive.event_id
        ):
            raise AgUiProjectionError("handoff lookahead conflicts with bound source window")


@dataclass(frozen=True, slots=True)
class ProjectionPagePlan:
    run: TaskRunHeader
    events: tuple[ProjectionEventPlan, ...]
    handoffs: tuple[ProjectionHandoffProof, ...] = ()

    def validate(
        self,
        page: TaskEventPage,
        scope: ProjectionScope,
        identity: AgUiRunIdentity,
        profile: AgUiProjectionProfile | None = None,
    ) -> None:
        if (
            type(self.events) is not tuple
            or type(self.handoffs) is not tuple
            or len(self.events) > MAX_CHECKPOINT_EVENTS
            or len(self.events) != len(page.events)
            or len(self.handoffs) > MAX_CHECKPOINT_EVENTS
        ):
            raise AgUiProjectionError("projection plan exceeds/mismatches Page coverage")
        if scope.projector_version != checkpoint_version(self.run, profile):
            raise AgUiProjectionError("unsupported checkpoint projector version")
        if not self.run.strict_coverage and strict_coverage_events(e.event for e in page.events):
            raise AgUiProjectionError("canonical Run privacy metadata contradicts its Page")
        anchor_id = self.run.anchor.event_id if self.run.anchor is not None else None
        if (
            scope.task_id != self.run.task_id
            or str(scope.task_id) != identity.thread_id
            or self.run.run_id != identity.run_id
            or scope.anchor_event_id != anchor_id
            or page.highwater != self.run.highwater
        ):
            raise AgUiProjectionError("projection plan belongs to another Task/run/snapshot")
        for entry, plan in zip(page.events, self.events, strict=True):
            source = plan.source
            if (
                entry.task_id != scope.task_id
                or source.task_id != entry.task_id
                or source.task_sequence != entry.task_sequence
                or source.event_id != entry.event.event_id
                or source.segment_id != entry.segment_id
                or source.segment_sequence != entry.segment_sequence
                or source.event_type != entry.event.event_type
            ):
                raise AgUiProjectionError("projection plan conflicts with canonical Event")
            if plan.projected and (
                self.run.control_only
                or (not self.run.legacy and self.run.anchor is None)
                or (self.run.stop is not None and entry.task_sequence >= self.run.stop)
            ):
                raise AgUiProjectionError("unbound/control-only run cannot project")
            if plan.eligible and (
                entry.task_sequence < self.run.start
                or (self.run.stop is not None and entry.task_sequence >= self.run.stop)
            ):
                raise AgUiProjectionError("eligible Event is outside the run window")
        pairs: set[tuple[int, int]] = set()
        for proof in self.handoffs:
            proof.validate(self.run)
            pair = (proof.commit.task_sequence, proof.receive.task_sequence)
            if pair in pairs:
                raise AgUiProjectionError("handoff lookahead repeats a canonical pair")
            pairs.add(pair)


def validate_restore_run(
    scope: ProjectionScope,
    run: TaskRunHeader,
    identity: AgUiRunIdentity,
    position: int,
    profile: AgUiProjectionProfile | None = None,
) -> None:
    anchor_id = run.anchor.event_id if run.anchor is not None else None
    if (
        scope.projector_version != checkpoint_version(run, profile)
        or run.task_id != scope.task_id
        or str(scope.task_id) != identity.thread_id
        or run.run_id != identity.run_id
        or scope.anchor_event_id != anchor_id
        or run.control_only
        or (not run.legacy and run.anchor is None)
        or not run.start <= position <= run.highwater
        or (run.stop is not None and position >= run.stop)
    ):
        raise AgUiProjectionError("checkpoint restore does not match the bound Task/run/window")
