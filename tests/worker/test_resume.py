from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId, new_session_id
from agent_storage import (
    SQLiteEventStore,
    SQLiteLeaseStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from zebra_agent_worker import (
    SessionClaimService,
    SessionRecoveryService,
    SessionResumeError,
    SessionResumeService,
)


def test_session_resume_service_resumes_running_session(tmp_path: Path) -> None:
    database_path = tmp_path / "resume.db"
    session_id = _seed_session(database_path, terminal=False)
    resume_service = SessionResumeService(_build_claim_service(database_path))

    resumed = resume_service.resume_session(
        session_id,
        worker_id="worker-a",
        resumed_at=datetime(2026, 6, 22, 0, 10, tzinfo=UTC),
        lease_ttl_seconds=30,
    )

    assert resumed.claimed.recovery.is_terminal is False
    assert resumed.claimed.recovery.session.status.value == "running"
    assert resumed.claimed.lease.worker_id == "worker-a"


def test_session_resume_service_rejects_terminal_session(tmp_path: Path) -> None:
    database_path = tmp_path / "resume.db"
    session_id = _seed_session(database_path, terminal=True)
    claim_service = _build_claim_service(database_path)
    lease_store = SQLiteLeaseStore(database_path)
    resume_service = SessionResumeService(claim_service)

    with pytest.raises(SessionResumeError, match="cannot resume terminal session"):
        resume_service.resume_session(
            session_id,
            worker_id="worker-a",
            resumed_at=datetime(2026, 6, 22, 0, 15, tzinfo=UTC),
            lease_ttl_seconds=30,
        )

    assert lease_store.get(session_id) is None


def _build_claim_service(database_path: Path) -> SessionClaimService:
    return SessionClaimService(
        SQLiteLeaseStore(database_path),
        SessionRecoveryService(
            SQLiteEventStore(database_path),
            SQLiteProjectionStore(database_path),
            SQLiteWorkspaceProjectionStore(database_path),
        ),
    )


def _seed_session(database_path: Path, *, terminal: bool) -> SessionId:
    event_store = SQLiteEventStore(database_path)
    session_id = new_session_id()
    created_at = datetime(2026, 6, 22, 0, 5, tzinfo=UTC)
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "Resume Session"},
            created_at=created_at,
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={
                "title": "Resume Session",
                "user_input": "continue",
                "workspace_root": str(Path("/tmp/resume-session")),
            },
            created_at=created_at,
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=2,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
            created_at=created_at,
        )
    )
    if terminal:
        event_store.append(
            SessionEvent.create(
                session_id=session_id,
                sequence=3,
                event_type=EventType.SESSION_COMPLETED,
                actor=EventActor.HARNESS,
                payload={"summary": "done"},
                created_at=created_at,
            )
        )
    return session_id
