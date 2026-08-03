from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.session_history import SessionHistoryMode, SessionHistoryRequest
from agent_storage import (
    PostgresEventStore,
    PostgresProjectionStore,
    PostgresSessionHistory,
    apply_postgres_migrations,
)


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    apply_postgres_migrations(dsn)
    return dsn


@pytest.fixture
def deployment_namespace(postgres_dsn: str):
    namespace = f"history-{uuid4()}"
    yield namespace
    _delete_namespace(postgres_dsn, namespace)


def test_postgres_history_matches_read_search_and_browse_contract(
    postgres_dsn: str,
    deployment_namespace: str,
) -> None:
    title_hit = _stored_session(postgres_dsn, deployment_namespace, "Needle title", "ordinary", 1)
    message_hit = _stored_session(postgres_dsn, deployment_namespace, "Other", "needle body", 2)
    PostgresEventStore(postgres_dsn, deployment_namespace=deployment_namespace).append(
        SessionEvent.create(
            session_id=message_hit,
            sequence=4,
            event_type=EventType.TOOL_EXECUTION_COMPLETED,
            actor=EventActor.TOOL,
            payload={"output": "SECRET-CONTROL-NEEDLE"},
            created_at=_at(2),
        )
    )
    scope = OpaqueAuthorityScope(authority_issuer="issuer", namespace_id="business-scope")
    history = PostgresSessionHistory(
        postgres_dsn,
        deployment_namespace=deployment_namespace,
        scope=scope,
    )

    browsed = history.query(SessionHistoryRequest(mode=SessionHistoryMode.BROWSE, limit=10))
    searched = history.query(
        SessionHistoryRequest(mode=SessionHistoryMode.SEARCH, query="needle", limit=10)
    )
    read = history.query(
        SessionHistoryRequest(
            mode=SessionHistoryMode.READ,
            session_id=str(message_hit),
            limit=2,
        )
    )

    assert [item.session_id for item in browsed.sessions] == [str(message_hit), str(title_hit)]
    assert [item.session_id for item in searched.sessions] == [str(title_hit), str(message_hit)]
    assert all("SECRET-CONTROL" not in (item.snippet or "") for item in searched.sessions)
    assert [(item.role, item.content) for item in read.messages] == [
        ("user", "needle body"),
        ("assistant", "assistant text"),
    ]
    assert read.total_count == 2
    assert read.next_offset is None


def test_postgres_history_scope_and_namespace_isolation(
    postgres_dsn: str,
    deployment_namespace: str,
) -> None:
    allowed = _stored_session(postgres_dsn, deployment_namespace, "Allowed", "shared", 1)
    denied = _stored_session(postgres_dsn, deployment_namespace, "Denied", "shared", 2)
    other_namespace = f"history-other-{uuid4()}"
    other = _stored_session(postgres_dsn, other_namespace, "Other", "shared", 3)
    try:
        history = PostgresSessionHistory(
            postgres_dsn,
            deployment_namespace=deployment_namespace,
            scope=OpaqueAuthorityScope(
                authority_issuer="issuer",
                namespace_id="business-scope",
                allowed_session_ids=(str(allowed),),
            ),
        )
        browsed = history.query(SessionHistoryRequest(mode=SessionHistoryMode.BROWSE, limit=10))
        denied_read = history.query(
            SessionHistoryRequest(mode=SessionHistoryMode.READ, session_id=str(denied))
        )
        other_read = PostgresSessionHistory(
            postgres_dsn,
            deployment_namespace=other_namespace,
            scope=OpaqueAuthorityScope(
                authority_issuer="issuer",
                namespace_id="business-scope",
                allowed_session_ids=(str(other),),
            ),
        ).query(SessionHistoryRequest(mode=SessionHistoryMode.READ, session_id=str(allowed)))

        assert [item.session_id for item in browsed.sessions] == [str(allowed)]
        assert denied_read.sessions == ()
        assert denied_read.messages == ()
        assert other_read.sessions == ()
        assert other_read.messages == ()
    finally:
        _delete_namespace(postgres_dsn, other_namespace)


def test_postgres_history_scoped_can_explicitly_deny_all(
    postgres_dsn: str,
    deployment_namespace: str,
) -> None:
    session_id = _stored_session(postgres_dsn, deployment_namespace, "Hidden", "hidden", 1)
    history = PostgresSessionHistory(
        postgres_dsn,
        deployment_namespace=deployment_namespace,
        scope=OpaqueAuthorityScope(authority_issuer="issuer", namespace_id="business-scope"),
    ).scoped(())

    result = history.query(SessionHistoryRequest(mode=SessionHistoryMode.BROWSE, limit=10))

    assert result.sessions == ()
    assert not history.query(
        SessionHistoryRequest(mode=SessionHistoryMode.READ, session_id=str(session_id))
    ).sessions


def _stored_session(
    dsn: str,
    namespace: str,
    title: str,
    prompt: str,
    minute: int,
) -> UUID:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title=title,
            user_input=prompt,
            workspace_root="/tmp/zebra-history",
            created_at=_at(minute),
        )
    )
    events = PostgresEventStore(dsn, deployment_namespace=namespace)
    for event in bootstrap.events:
        events.append(event)
    events.append(
        SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=3,
            event_type=EventType.MODEL_RESPONSE_RECEIVED,
            actor=EventActor.HARNESS,
            payload={"assistant_message": "assistant text"},
            created_at=_at(minute),
        )
    )
    PostgresProjectionStore(dsn, deployment_namespace=namespace).save_session(bootstrap.session)
    return bootstrap.session.session_id


def _delete_namespace(dsn: str, namespace: str) -> None:
    with psycopg.connect(dsn) as connection:
        for table in ("session_events", "session_projections", "session_streams"):
            connection.execute(
                f"DELETE FROM {table} WHERE deployment_namespace = %s",
                (namespace,),
            )


def _at(minute: int) -> datetime:
    return datetime(2026, 7, 15, tzinfo=UTC) + timedelta(minutes=minute)
