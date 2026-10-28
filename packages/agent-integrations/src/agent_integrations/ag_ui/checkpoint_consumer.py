"""Bounded background materialization; callers own process lifetime, not SSE."""

import logging
from collections.abc import Callable
from dataclasses import replace
from time import monotonic

from agent_core.domain.identifiers import TaskId
from agent_core.ports.agent_tasks import AgentTaskPort
from agent_core.ports.task_projection_checkpoints import (
    CheckpointConflict,
    CheckpointNotReady,
    CheckpointStale,
    ProjectionCheckpointHead,
    ProjectionScope,
)
from agent_core.ports.task_projection_work import (
    PROJECTION_WORK_SECONDS,
    ProjectionWork,
    TaskProjectionWorkPort,
)
from agent_core.ports.task_read_summaries import TaskReadSummaryPort
from agent_core.ports.task_replay import TaskRunHeader

from agent_integrations.ag_ui.binding_resolution import (
    BindingResolutionPending,
    advance_binding_resolution,
)
from agent_integrations.ag_ui.checkpoint_binding import build_projection_page_plan
from agent_integrations.ag_ui.checkpoint_materializer import AgUiCheckpointMaterializer
from agent_integrations.ag_ui.checkpoint_plan import (
    AG_UI_CHECKPOINT_VERSION,
    AG_UI_COVERAGE_CHECKPOINT_VERSION,
    checkpoint_version,
)
from agent_integrations.ag_ui.contracts import AgUiRunIdentity
from agent_integrations.ag_ui.profiles import AgUiProjectionProfile

logger = logging.getLogger(__name__)


class AgUiCheckpointConsumer:
    """One Page per selected work item, bounded round-robin discovery.

    Duplicate consumers use checkpoint CAS and the work revision ACK. Long model
    or tool calls are unrelated to this consumer. No execution API is available.
    ponytail: a tick's time bound is checked between Store operations; adapters
    must also bound their own I/O, since a Python deadline cannot cancel SQL.
    """

    def __init__(
        self,
        tasks: AgentTaskPort,
        work: TaskProjectionWorkPort,
        *,
        namespace: str,
        read_summaries: TaskReadSummaryPort | None = None,
        checkpoint_committed: Callable[[ProjectionCheckpointHead], object] | None = None,
        notification_required: bool = False,
        profile: AgUiProjectionProfile | None = None,
    ) -> None:
        if (
            not isinstance(namespace, str)
            or not namespace.strip()
            or namespace != namespace.strip()
            or len(namespace.encode()) > 256
        ):
            raise ValueError("invalid projection consumer namespace")
        if notification_required and checkpoint_committed is None:
            raise ValueError("cloud checkpoint publication requires a callback")
        self.notification_required = notification_required
        self._notification_retry: dict[ProjectionScope, tuple[int, float, float]] = {}
        self.tasks, self.work, self.namespace = tasks, work, namespace
        self.read_summaries = read_summaries
        self.checkpoint_committed = checkpoint_committed
        self.profile = profile
        self.materializer = AgUiCheckpointMaterializer(tasks, profile=profile)
        self._after_scope: ProjectionScope | None = None
        self._after_repair: TaskId | None = None
        self._repair_turn = True
        self._repair_retry_at = 0.0

    def _scope(self, scope: ProjectionScope) -> None:
        versions = (
            {self.profile.checkpoint_version(), self.profile.checkpoint_version(coverage=True)}
            if self.profile is not None
            else {AG_UI_CHECKPOINT_VERSION, AG_UI_COVERAGE_CHECKPOINT_VERSION}
        )
        if scope.namespace != self.namespace or scope.projector_version not in versions:
            raise CheckpointConflict("projection work belongs to another namespace/version")

    def _repair_task(self, task: TaskId) -> bool:
        # False means a bounded batch advanced, not that the Task failed.
        if not self.tasks.backfill_event_positions(task, limit=256):
            return False
        if not self.tasks.backfill_replay_headers(
            task,
            limit=128,
            max_bytes=1_048_576,
            # This is maintenance, not an SSE read. The native two-second I/O
            # budget includes cold DNS/connect and transaction exit; 100ms
            # repeatedly expires before DNS can populate its address cache.
            timeout_seconds=PROJECTION_WORK_SECONDS,
        ):
            return False
        if not self.tasks.backfill_projection_sources(task, limit=256):
            return False
        if self.read_summaries is not None and not self.read_summaries.backfill_read_summary(task):
            return False
        self.work.repair_projection_work(task, limit=256)
        return True

    def repair_once(self) -> int:
        if monotonic() < self._repair_retry_at:
            return 0
        repairs = self.work.read_projection_work_repairs(limit=1, after_task_id=self._after_repair)
        if not repairs:
            self._after_repair = None
            return 0
        for repair in repairs:
            self._after_repair = repair.scope.task_id
            self._scope(repair.scope)
            try:
                return int(self._repair_task(repair.scope.task_id))
            except Exception as exc:
                # ponytail: one-second consumer-local cooldown, not a durable
                # execution lease. The round-robin cursor still reaches other
                # Tasks; restart safely retries from canonical source metadata.
                self._repair_retry_at = monotonic() + 1.0
                logger.warning(
                    "AG-UI projection repair deferred task=%s error=%s",
                    repair.scope.task_id,
                    type(exc).__name__,
                )
        return 0

    def _defer(self, work: ProjectionWork, exc: Exception) -> None:
        logger.warning(
            "AG-UI projection work deferred task=%s error=%s",
            work.scope.task_id,
            type(exc).__name__,
        )
        try:
            self._scope(work.scope)  # Never mutate a forged cross-namespace work item.
            self.work.defer_projection_work(
                work,
                problem_code="integrity"
                if isinstance(exc, CheckpointConflict)
                else "projection_failed",
                retry_after_seconds=None if isinstance(exc, CheckpointConflict) else 1.0,
            )
        except Exception as failure:
            logger.warning(
                "AG-UI projection problem persistence failed: %s", type(failure).__name__
            )

    def _notify_checkpoint(self, head: ProjectionCheckpointHead) -> bool:
        scope, now = head.scope, monotonic()
        if self.checkpoint_committed is None:
            return not self.notification_required
        try:
            if self.checkpoint_committed(head) is False:
                raise RuntimeError("checkpoint publication unconfirmed")
        except Exception:
            # Physical notification retries never consume the durable eight-attempt failure cap.
            stale = [
                key
                for key, (_, _, touched) in self._notification_retry.items()
                if now - touched > 300
            ]
            for key in stale:
                del self._notification_retry[key]
            failures = self._notification_retry.get(scope, (0, 0, now))[0] + 1
            if scope not in self._notification_retry and len(self._notification_retry) >= 512:
                del self._notification_retry[
                    min(self._notification_retry, key=lambda key: self._notification_retry[key][2])
                ]
            self._notification_retry[scope] = (
                failures,
                now + min(30, 2 ** min(failures - 1, 5)),
                now,
            )
            logger.warning("AG-UI checkpoint notification unavailable")
            return False
        self._notification_retry.pop(scope, None)
        return True

    def materialize_once(self, work: ProjectionWork) -> bool:
        self._scope(work.scope)
        run = self.tasks.read_run_header(
            work.scope.task_id,
            work.run_id,
            through_sequence=work.requested_through,
        )
        # Work targets can close before a later Task-wide privacy marker. Public
        # replay uses today's strict scope, so rebuild that same captured window.
        latest = self.tasks.read_run_header(work.scope.task_id, work.run_id)
        if (
            not isinstance(latest, TaskRunHeader)
            or latest.task_id != run.task_id
            or latest.run_id != run.run_id
            or latest.anchor != run.anchor
            or latest.start != run.start
            or latest.highwater < run.highwater
        ):
            raise CheckpointConflict("latest privacy header conflicts with canonical Run")
        if latest.strict_coverage and not run.strict_coverage:
            run = replace(run, strict_coverage=True)
        if (
            run.anchor is None
            or run.control_only
            or run.legacy
            or run.task_id != work.scope.task_id
            or run.run_id != work.run_id
            or run.anchor.event_id != work.scope.anchor_event_id
            or run.start != work.anchor_sequence
            or run.highwater != work.requested_through
        ):
            raise CheckpointConflict("projection work conflicts with its canonical Run")
        if work.scope.projector_version != checkpoint_version(run, self.profile):
            # No ACK, timer or repeated privacy poll. Source-owned routing repair
            # wakes old closed anchors after a late flip, preserving failure caps.
            self.work.defer_projection_work(work, problem_code="not_ready")
            return False
        summary_ready = self.read_summaries is None or self.read_summaries.backfill_read_summary(
            work.scope.task_id
        )
        head = self.tasks.read_checkpoint_head(work.scope)
        if head.through_sequence >= work.requested_through:
            if not self._notify_checkpoint(head) or not summary_ready:
                return False
            return self.work.complete_projection_work(work, expected_through=work.requested_through)
        identity = AgUiRunIdentity(
            session_id=run.anchor.segment_id,
            thread_id=str(run.task_id),
            run_id=run.run_id,
        )
        page = self.tasks.read_event_page(
            run.task_id,
            head.through_sequence,
            limit=256,
            max_bytes=1_048_576,
            through_sequence=run.highwater,
        )
        try:
            plan = build_projection_page_plan(
                self.tasks,
                page,
                run,
                work.scope,
                identity,
                closed_through=work.closed_through,
                profile=self.profile,
            )
            transition = self.materializer.prepare_page(page, plan, work.scope, identity)
            if transition is None:
                return False
            committed = self.tasks.commit_projection_page(transition)
        except BindingResolutionPending as exc:
            if exc.resolved_through < exc.required_through:
                try:
                    advance_binding_resolution(self.tasks, run, work.scope, limit=256)
                except CheckpointStale:
                    return False
            else:
                # An open Run's absent membership may change on a later causal receive.
                # Persist the dependency wait; only new source/closure wakes it, not a timer.
                self.work.defer_projection_work(
                    work,
                    problem_code="not_ready" if exc.reason == "admission" else "budget",
                )
            return False
        except CheckpointStale:
            # Only a confirmed frontier race is benign; identity conflicts still fail closed.
            return False
        if not self._notify_checkpoint(committed):
            return False
        if committed.through_sequence >= work.requested_through and summary_ready:
            self.work.complete_projection_work(work, expected_through=committed.through_sequence)
        return True

    def poll_once(self, *, limit: int = 32, budget_seconds: float = 0.05) -> int:
        if type(limit) is not int or not 1 <= limit <= 32 or not 0 < budget_seconds <= 2:
            raise ValueError("invalid projection consumer tick budget")
        deadline = monotonic() + budget_seconds
        self.work.retry_due_projection_work(limit=limit)
        # Alternate maintenance precedence so neither legacy repair nor live work starves.
        repaired = self._repair_turn
        progressed = self.repair_once() if repaired else 0
        self._repair_turn = not repaired
        pending = self.work.read_pending_projection_work(limit=limit, after_scope=self._after_scope)
        if not pending:
            self._after_scope = None
            return progressed + (0 if repaired else self.repair_once())
        for work in pending:
            if monotonic() >= deadline:
                break
            self._after_scope = work.scope
            self._scope(work.scope)
            retry = self._notification_retry.get(work.scope)
            if retry is not None and monotonic() < retry[1]:
                continue
            try:
                try:
                    progressed += self.materialize_once(work)
                except CheckpointNotReady:
                    # Bounded repair progress is not a failed execution attempt.
                    self._scope(work.scope)
                    self._repair_task(work.scope.task_id)
            except Exception as exc:
                self._defer(work, exc)
        return progressed
