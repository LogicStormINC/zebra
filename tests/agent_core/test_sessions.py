from datetime import UTC, datetime

import pytest
from agent_core.domain.sessions import Session, SessionStatus


def test_session_create_defaults_to_created() -> None:
    session = Session.create(title="bootstrap")

    assert session.status is SessionStatus.CREATED
    assert session.current_sequence == 0
    assert session.created_at == session.updated_at


def test_session_allows_valid_transition_path() -> None:
    created = Session.create(title="bootstrap", created_at=datetime.now(UTC))
    ready = created.transition_to(SessionStatus.READY)
    running = ready.transition_to(SessionStatus.RUNNING)
    completed = running.transition_to(SessionStatus.COMPLETED)

    assert ready.status is SessionStatus.READY
    assert running.status is SessionStatus.RUNNING
    assert completed.status is SessionStatus.COMPLETED


def test_session_rejects_invalid_transition() -> None:
    session = Session.create(title="bootstrap")

    with pytest.raises(ValueError, match="invalid session transition"):
        session.transition_to(SessionStatus.COMPLETED)


def test_session_advance_sequence_increments_monotonically() -> None:
    session = Session.create(title="bootstrap")

    next_session = session.advance_sequence().advance_sequence()

    assert next_session.current_sequence == 2
