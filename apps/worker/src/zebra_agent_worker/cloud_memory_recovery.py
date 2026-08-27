"""Bounded recovery of Cloud Memory finalization after a lost Worker response."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from agent_core.application import SessionTitleService
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseConflictError
from agent_core.domain.sessions import SessionStatus
from agent_core.ports import (
    EventStorePort,
    GovernedMemoryStorePort,
    IdempotencyRecord,
    IdempotencyStorePort,
    ProjectionStorePort,
    WorkspaceProjectionStorePort,
)

from zebra_agent_worker.claims import SessionClaimService
from zebra_agent_worker.cloud_memory_finalization import (
    finalize_cloud_memory,
    memory_completion_revision,
)
from zebra_agent_worker.execution_finalization import WorkerExecutionError
from zebra_agent_worker.lease_heartbeat import LeaseHeartbeat
from zebra_agent_worker.recovery import SessionRecoveryError
from zebra_agent_worker.worker_projection import WorkerProjectionRecorderFactory

TITLE_RETRY_COOLDOWN = timedelta(minutes=15)
_TITLE_RETRY_ACTION = "worker-title-retry"
MEMORY_RECOVERY_ACTION = "worker-memory-finalization-recovery"
_MEMORY_RECOVERY_HASH = "worker-memory-finalization-recovery-v1"


def _title_retry_key(session_id: SessionId, bucket: int) -> str:
    return f"worker-title-retry:{session_id}:{bucket}"


def _reserve_title_attempt(
    store: IdempotencyStorePort,
    session_id: SessionId,
    attempted_at: datetime,
) -> bool:
    """Claim one paid title attempt across Workers for a rolling window."""

    bucket_seconds = TITLE_RETRY_COOLDOWN.total_seconds()
    bucket = int(attempted_at.timestamp() // bucket_seconds)
    for probe in (bucket, bucket - 1):
        record = store.get(
            action=_TITLE_RETRY_ACTION,
            idempotency_key=_title_retry_key(session_id, probe),
        )
        if record is None:
            continue
        raw_attempted_at = record.response_body.get("attempted_at")
        if not isinstance(raw_attempted_at, str):
            raise ValueError("durable title retry record has no attempted_at")
        previous_attempt = datetime.fromisoformat(raw_attempted_at)
        if previous_attempt.tzinfo is None:
            raise ValueError("durable title retry timestamp must be timezone-aware")
        if attempted_at - previous_attempt < TITLE_RETRY_COOLDOWN:
            return False

    reservation_id = str(uuid4())
    proposed = IdempotencyRecord(
        action=_TITLE_RETRY_ACTION,
        idempotency_key=_title_retry_key(session_id, bucket),
        request_hash="title-retry-v1",
        status_code=204,
        response_body={
            "attempted_at": attempted_at.isoformat(),
            "reservation_id": reservation_id,
        },
        created_at=attempted_at,
    )
    stored = store.save(proposed)
    return stored.response_body.get("reservation_id") == reservation_id


def memory_recovery_key(session_id: SessionId, completion_revision: int) -> str:
    return f"{session_id}:{completion_revision}"


def _mark_memory_recovered(
    store: IdempotencyStorePort | None,
    session_id: SessionId,
    completion_revision: int,
    recovered_at: datetime,
) -> None:
    if store is None:
        return
    store.save(
        IdempotencyRecord(
            action=MEMORY_RECOVERY_ACTION,
            idempotency_key=memory_recovery_key(session_id, completion_revision),
            request_hash=_MEMORY_RECOVERY_HASH,
            status_code=204,
            response_body={
                "session_id": str(session_id),
                "completion_revision": completion_revision,
            },
            created_at=recovered_at,
        )
    )


class CloudMemoryFinalizationRecovery:
    """Finalize recently completed Cloud sessions without resuming their harness."""

    def __init__(
        self,
        *,
        claim_service: SessionClaimService,
        recorder_factory: WorkerProjectionRecorderFactory,
        memory_store: GovernedMemoryStorePort,
        idempotency_store: IdempotencyStorePort | None = None,
        deployment_namespace: str,
        event_store: EventStorePort,
        projection_store: ProjectionStorePort,
        workspace_store: WorkspaceProjectionStorePort,
        title_service_factory: Callable[[], SessionTitleService],
    ) -> None:
        self._claim_service = claim_service
        self._recorder_factory = recorder_factory
        self._memory_store = memory_store
        self._idempotency_store = idempotency_store
        self._deployment_namespace = deployment_namespace
        self._event_store = event_store
        self._title_attempts: dict[SessionId, datetime] = {}
        self._projection_store = projection_store
        self._workspace_store = workspace_store
        self._title_service_factory = title_service_factory

    def recover(
        self,
        session_id: SessionId,
        *,
        worker_id: str,
        recovered_at: datetime,
        lease_ttl_seconds: int,
    ) -> bool:
        claimed = self._claim_service.claim_session(
            session_id,
            worker_id=worker_id,
            claimed_at=recovered_at,
            lease_ttl_seconds=lease_ttl_seconds,
        )
        with LeaseHeartbeat(
            self._claim_service,
            claimed.lease,
            lease_ttl_seconds=lease_ttl_seconds,
        ) as heartbeat:
            if claimed.recovery.session.status not in {
                SessionStatus.COMPLETED,
                SessionStatus.AWAITING_TURN,
            }:
                return False
            recorder = self._recorder_factory.build(
                session=claimed.recovery.session,
                workspace=claimed.recovery.workspace,
                lease=claimed.lease,
                ownership_check=heartbeat.require_owned,
            )
            finalized = finalize_cloud_memory(
                recorder=recorder,
                memory_store=self._memory_store,
                deployment_namespace=self._deployment_namespace,
                event_store=self._event_store,
                projection_store=self._projection_store,
                workspace_store=self._workspace_store,
                # The recovery claim holds the lease and a fenced recorder:
                # commit the missing side chain instead of no-oping on it
                # (ADR-026 §6 — the crash-before-commit case).
                started_at=recovered_at,
                allow_commit=True,
            )
            if not finalized:
                return False
            events = self._event_store.list_for_session(session_id)
            _mark_memory_recovered(
                self._idempotency_store,
                session_id,
                memory_completion_revision(events, recorder.session),
                recovered_at,
            )
            if any(event.event_type is EventType.SESSION_TITLE_UPDATED for event in events):
                return True
            now = recovered_at
            if self._idempotency_store is not None:
                if not _reserve_title_attempt(self._idempotency_store, session_id, now):
                    return True
            elif (
                last_attempt := self._title_attempts.get(session_id)
            ) is not None and now - last_attempt < TITLE_RETRY_COOLDOWN:
                return True
            self._title_attempts[session_id] = now
            title_event = self._title_service_factory().generate(
                session=recorder.session,
                events=events,
                next_sequence=recorder.next_sequence,
            )
            if title_event is not None:
                recorder.append_event(title_event)
                self._title_attempts.pop(session_id, None)
            return True


def recover_completed_cloud_memory(
    *,
    worker_id: str,
    batch_size: int,
    lease_ttl_seconds: int,
    recovery: Any,
    projection_store: Any,
) -> None:
    if recovery is None:
        return
    pending_reader = getattr(projection_store, "list_memory_recovery_sessions", None)
    pending = (
        pending_reader(limit=max(batch_size, 1), recovery_action=MEMORY_RECOVERY_ACTION)
        if callable(pending_reader)
        else []
    )
    # Recent Sessions retain the existing best-effort title retry behavior. The
    # PostgreSQL pending reader is durable and oldest-first, so Memory recovery
    # itself no longer depends on a moving recent-Session window.
    recent = projection_store.list_recent_sessions(limit=max(batch_size, 32))
    sessions = {session.session_id: session for session in (*pending, *recent)}
    for session in sessions.values():
        # COMPLETED: legacy/one-shot finalization; AWAITING_TURN: a
        # conversation Turn closed but its fenced Memory/title side
        # chain may still be missing after a Worker crash (ADR-026 §6).
        if session.status not in {
            SessionStatus.COMPLETED,
            SessionStatus.AWAITING_TURN,
        }:
            continue
        try:
            recovery.recover(
                session.session_id,
                worker_id=worker_id,
                recovered_at=datetime.now(UTC),
                lease_ttl_seconds=lease_ttl_seconds,
            )
        except (LeaseConflictError, SessionRecoveryError, WorkerExecutionError):
            # Deterministic configuration/projection/contract errors are
            # deliberately NOT swallowed: they must surface instead of
            # forming an invisible hot loop over corrupted sessions.
            continue
