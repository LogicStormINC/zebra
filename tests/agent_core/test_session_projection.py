from datetime import UTC, datetime, timedelta

import pytest
from agent_core.application.session_projection import SessionProjectionError, rebuild_session
from agent_core.contracts import EventPayloadValidationError
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_core.domain.sessions import SessionStatus


def test_rebuild_session_applies_status_transitions() -> None:
    session_id = new_session_id()
    created_at = datetime(2026, 6, 18, 10, 0, tzinfo=UTC)
    events = [
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={"title": "bootstrap"},
            created_at=created_at,
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload={"title": "bootstrap", "user_input": "continue"},
            created_at=created_at + timedelta(seconds=1),
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=2,
            event_type=EventType.MODEL_REQUEST_STARTED,
            actor=EventActor.HARNESS,
            created_at=created_at + timedelta(seconds=2),
        ),
        SessionEvent.create(
            session_id=session_id,
            sequence=3,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.SYSTEM,
            created_at=created_at + timedelta(seconds=3),
        ),
    ]

    session = rebuild_session(events)

    assert session.title == "bootstrap"
    assert session.status is SessionStatus.COMPLETED
    assert session.current_sequence == 3
    assert session.updated_at == created_at + timedelta(seconds=3)


def test_rebuild_session_requires_session_created_first() -> None:
    with pytest.raises(SessionProjectionError, match="first event must be session_created"):
        rebuild_session(
            [
                SessionEvent.create(
                    session_id=new_session_id(),
                    sequence=0,
                    event_type=EventType.TASK_PREPARED,
                    actor=EventActor.HARNESS,
                    payload={"title": "bootstrap", "user_input": "continue"},
                    created_at=datetime(2026, 6, 18, 10, 0, tzinfo=UTC),
                )
            ]
        )


def test_rebuild_session_rejects_non_contiguous_sequences() -> None:
    session_id = new_session_id()
    created_at = datetime(2026, 6, 18, 10, 0, tzinfo=UTC)

    with pytest.raises(SessionProjectionError, match="expected event sequence 1, got 2"):
        rebuild_session(
            [
                SessionEvent.create(
                    session_id=session_id,
                    sequence=0,
                    event_type=EventType.SESSION_CREATED,
                    actor=EventActor.SYSTEM,
                    payload={"title": "bootstrap"},
                    created_at=created_at,
                ),
                SessionEvent.create(
                    session_id=session_id,
                    sequence=2,
                    event_type=EventType.TASK_PREPARED,
                    actor=EventActor.HARNESS,
                    payload={"title": "bootstrap", "user_input": "continue"},
                    created_at=created_at + timedelta(seconds=1),
                ),
            ]
        )


def test_rebuild_session_applies_approval_granted_transition() -> None:
    session_id = new_session_id()
    created_at = datetime(2026, 6, 18, 10, 0, tzinfo=UTC)

    session = rebuild_session(
        [
            SessionEvent.create(
                session_id=session_id,
                sequence=0,
                event_type=EventType.SESSION_CREATED,
                actor=EventActor.SYSTEM,
                payload={"title": "approval grant"},
                created_at=created_at,
            ),
            SessionEvent.create(
                session_id=session_id,
                sequence=1,
                event_type=EventType.TASK_PREPARED,
                actor=EventActor.HARNESS,
                payload={"title": "approval grant", "user_input": "continue"},
                created_at=created_at + timedelta(seconds=1),
            ),
            SessionEvent.create(
                session_id=session_id,
                sequence=2,
                event_type=EventType.HARNESS_ATTEMPT_STARTED,
                actor=EventActor.HARNESS,
                created_at=created_at + timedelta(seconds=2),
            ),
            SessionEvent.create(
                session_id=session_id,
                sequence=3,
                event_type=EventType.APPROVAL_REQUESTED,
                actor=EventActor.POLICY,
                created_at=created_at + timedelta(seconds=3),
            ),
            SessionEvent.create(
                session_id=session_id,
                sequence=4,
                event_type=EventType.APPROVAL_GRANTED,
                actor=EventActor.USER,
                created_at=created_at + timedelta(seconds=4),
            ),
        ]
    )

    assert session.status is SessionStatus.RUNNING
    assert session.current_sequence == 4


def test_rebuild_session_applies_approval_rejected_transition() -> None:
    session_id = new_session_id()
    created_at = datetime(2026, 6, 18, 10, 0, tzinfo=UTC)

    session = rebuild_session(
        [
            SessionEvent.create(
                session_id=session_id,
                sequence=0,
                event_type=EventType.SESSION_CREATED,
                actor=EventActor.SYSTEM,
                payload={"title": "approval reject"},
                created_at=created_at,
            ),
            SessionEvent.create(
                session_id=session_id,
                sequence=1,
                event_type=EventType.TASK_PREPARED,
                actor=EventActor.HARNESS,
                payload={"title": "approval reject", "user_input": "continue"},
                created_at=created_at + timedelta(seconds=1),
            ),
            SessionEvent.create(
                session_id=session_id,
                sequence=2,
                event_type=EventType.HARNESS_ATTEMPT_STARTED,
                actor=EventActor.HARNESS,
                created_at=created_at + timedelta(seconds=2),
            ),
            SessionEvent.create(
                session_id=session_id,
                sequence=3,
                event_type=EventType.APPROVAL_REQUESTED,
                actor=EventActor.POLICY,
                created_at=created_at + timedelta(seconds=3),
            ),
            SessionEvent.create(
                session_id=session_id,
                sequence=4,
                event_type=EventType.APPROVAL_REJECTED,
                actor=EventActor.USER,
                created_at=created_at + timedelta(seconds=4),
            ),
        ]
    )

    assert session.status is SessionStatus.FAILED
    assert session.current_sequence == 4


def test_rebuild_session_requires_title_in_created_event() -> None:
    session_id = new_session_id()
    created_at = datetime(2026, 6, 18, 10, 0, tzinfo=UTC)

    with pytest.raises(EventPayloadValidationError, match="invalid payload"):
        SessionEvent.create(
            session_id=session_id,
            sequence=0,
            event_type=EventType.SESSION_CREATED,
            actor=EventActor.SYSTEM,
            payload={},
            created_at=created_at,
        )


def test_rebuild_session_persists_proxy_approval_context() -> None:
    session_id = new_session_id()
    created_at = datetime(2026, 6, 18, 11, 0, tzinfo=UTC)

    session = rebuild_session(
        [
            SessionEvent.create(
                session_id=session_id,
                sequence=0,
                event_type=EventType.SESSION_CREATED,
                actor=EventActor.SYSTEM,
                payload={"title": "proxy approval"},
                created_at=created_at,
            ),
            SessionEvent.create(
                session_id=session_id,
                sequence=1,
                event_type=EventType.TASK_PREPARED,
                actor=EventActor.HARNESS,
                payload={"title": "proxy approval", "user_input": "continue"},
                created_at=created_at + timedelta(milliseconds=500),
            ),
            SessionEvent.create(
                session_id=session_id,
                sequence=2,
                event_type=EventType.HARNESS_ATTEMPT_STARTED,
                actor=EventActor.HARNESS,
                created_at=created_at + timedelta(milliseconds=750),
            ),
            SessionEvent.create(
                session_id=session_id,
                sequence=3,
                event_type=EventType.APPROVAL_REQUESTED,
                actor=EventActor.POLICY,
                payload={
                    "tool_name": "mcp.github.create_pull_request",
                    "reason": "proxy-routed external tool execution in test",
                    "policy_profile": "full_access",
                    "route": "mcp_proxy",
                    "target": "github.create_pull_request",
                    "network_profile": "mcp-proxy-only",
                    "scope": [
                        "tool:mcp.github.create_pull_request",
                        "route:mcp_proxy",
                    ],
                },
                created_at=created_at + timedelta(seconds=1),
            ),
            SessionEvent.create(
                session_id=session_id,
                sequence=4,
                event_type=EventType.APPROVAL_GRANTED,
                actor=EventActor.USER,
                payload={"operator": "alice", "reason": "approved"},
                created_at=created_at + timedelta(seconds=2),
            ),
        ]
    )

    assert session.status is SessionStatus.RUNNING
    assert session.approval_context is not None
    assert session.approval_context.tool_name == "mcp.github.create_pull_request"
    assert session.approval_context.route == "mcp_proxy"
    assert session.approval_context.target == "github.create_pull_request"
    assert session.approval_context.network_profile == "mcp-proxy-only"
    assert session.approval_context.scope == (
        "tool:mcp.github.create_pull_request",
        "route:mcp_proxy",
    )
