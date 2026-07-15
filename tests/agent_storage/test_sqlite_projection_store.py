from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.clarifications import ClarificationContext
from agent_core.domain.sessions import ApprovalContext, Session, SessionStatus
from agent_storage import SQLiteProjectionStore


def test_sqlite_projection_store_saves_and_loads_session(tmp_path: Path) -> None:
    store = SQLiteProjectionStore(tmp_path / "projections.db")
    created_at = datetime(2026, 6, 19, 23, 15, tzinfo=UTC)
    session = Session.create(title="Stored Session", created_at=created_at).model_copy(
        update={
            "status": SessionStatus.RUNNING,
            "current_sequence": 3,
            "updated_at": created_at,
        }
    )

    store.save_session(session)

    loaded = store.get_session(session.session_id)

    assert loaded == session


def test_sqlite_projection_store_returns_none_for_unknown_session(tmp_path: Path) -> None:
    store = SQLiteProjectionStore(tmp_path / "projections.db")
    session = Session.create(
        title="Unknown Session",
        created_at=datetime(2026, 6, 19, 23, 20, tzinfo=UTC),
    )

    assert store.get_session(session.session_id) is None


def test_sqlite_projection_store_lists_ready_sessions_in_update_order(tmp_path: Path) -> None:
    store = SQLiteProjectionStore(tmp_path / "projections.db")
    base_time = datetime(2026, 6, 19, 23, 30, tzinfo=UTC)
    first = Session.create(title="first", created_at=base_time).model_copy(
        update={
            "status": SessionStatus.READY,
            "updated_at": base_time,
        }
    )
    second = Session.create(title="second", created_at=base_time).model_copy(
        update={
            "status": SessionStatus.READY,
            "updated_at": base_time.replace(minute=31),
        }
    )
    running = Session.create(title="running", created_at=base_time).model_copy(
        update={
            "status": SessionStatus.RUNNING,
            "updated_at": base_time.replace(minute=32),
        }
    )
    store.save_session(second)
    store.save_session(running)
    store.save_session(first)

    ready = store.list_ready_sessions(limit=10)

    assert [session.session_id for session in ready] == [first.session_id, second.session_id]


def test_sqlite_projection_store_respects_ready_session_limit(tmp_path: Path) -> None:
    store = SQLiteProjectionStore(tmp_path / "projections.db")
    base_time = datetime(2026, 6, 19, 23, 40, tzinfo=UTC)
    first = Session.create(title="first", created_at=base_time).model_copy(
        update={"status": SessionStatus.READY, "updated_at": base_time}
    )
    second = Session.create(title="second", created_at=base_time).model_copy(
        update={
            "status": SessionStatus.READY,
            "updated_at": base_time.replace(minute=41),
        }
    )
    store.save_session(first)
    store.save_session(second)

    ready = store.list_ready_sessions(limit=1)

    assert [session.session_id for session in ready] == [first.session_id]


def test_sqlite_projection_store_lists_recent_sessions_newest_first(tmp_path: Path) -> None:
    store = SQLiteProjectionStore(tmp_path / "projections.db")
    base_time = datetime(2026, 6, 20, 0, 0, tzinfo=UTC)
    older = Session.create(title="older", created_at=base_time).model_copy(
        update={"updated_at": base_time}
    )
    newest = Session.create(title="newest", created_at=base_time).model_copy(
        update={
            "status": SessionStatus.COMPLETED,
            "updated_at": base_time.replace(minute=2),
        }
    )
    middle = Session.create(title="middle", created_at=base_time).model_copy(
        update={
            "status": SessionStatus.RUNNING,
            "updated_at": base_time.replace(minute=1),
        }
    )
    for session in (older, newest, middle):
        store.save_session(session)

    recent = store.list_recent_sessions(limit=10)

    assert [session.session_id for session in recent] == [
        newest.session_id,
        middle.session_id,
        older.session_id,
    ]


def test_sqlite_projection_store_bounds_recent_sessions(tmp_path: Path) -> None:
    store = SQLiteProjectionStore(tmp_path / "projections.db")
    base_time = datetime(2026, 6, 20, 0, 10, tzinfo=UTC)
    sessions = [
        Session.create(title=f"session-{index}", created_at=base_time).model_copy(
            update={"updated_at": base_time.replace(minute=10 + index)}
        )
        for index in range(3)
    ]
    for session in sessions:
        store.save_session(session)

    assert store.list_recent_sessions(limit=0) == []
    assert [session.title for session in store.list_recent_sessions(limit=2)] == [
        "session-2",
        "session-1",
    ]


def test_sqlite_projection_store_round_trips_approval_context(tmp_path: Path) -> None:
    store = SQLiteProjectionStore(tmp_path / "projections.db")
    created_at = datetime(2026, 6, 29, 11, 0, tzinfo=UTC)
    session = Session.create(title="Approval Context", created_at=created_at).model_copy(
        update={
            "status": SessionStatus.WAITING_APPROVAL,
            "updated_at": created_at,
            "current_sequence": 4,
            "approval_context": ApprovalContext(
                tool_name="mcp.github.create_pull_request",
                reason="proxy-routed external tool execution in test",
                policy_profile="full_access",
                route="mcp_proxy",
                target="github.create_pull_request",
                network_profile="mcp-proxy-only",
                scope=(
                    "tool:mcp.github.create_pull_request",
                    "route:mcp_proxy",
                ),
            ),
        }
    )

    store.save_session(session)
    loaded = store.get_session(session.session_id)

    assert loaded == session


def test_sqlite_projection_store_repeated_reads_keep_approval_context_stable(
    tmp_path: Path,
) -> None:
    store = SQLiteProjectionStore(tmp_path / "projections.db")
    created_at = datetime(2026, 6, 29, 11, 30, tzinfo=UTC)
    session = Session.create(title="Stable Approval Context", created_at=created_at).model_copy(
        update={
            "status": SessionStatus.WAITING_APPROVAL,
            "updated_at": created_at,
            "current_sequence": 5,
            "approval_context": ApprovalContext(
                tool_name="mcp.github.create_pull_request",
                reason="proxy-routed external tool execution in test",
                policy_profile="full_access",
                route="mcp_proxy",
                target="github.create_pull_request",
                network_profile="mcp-proxy-only",
                scope=(
                    "tool:mcp.github.create_pull_request",
                    "route:mcp_proxy",
                    "network_profile:mcp-proxy-only",
                ),
            ),
        }
    )

    store.save_session(session)
    first = store.get_session(session.session_id)
    second = store.get_session(session.session_id)

    assert first is not None
    assert second is not None
    assert first.approval_context is not None
    assert second.approval_context is not None
    assert first.approval_context.to_mapping() == second.approval_context.to_mapping()


def test_sqlite_projection_store_round_trips_clarification_context(tmp_path: Path) -> None:
    database_path = tmp_path / "projections.db"
    created_at = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
    clarification_id = "00000000-0000-0000-0000-000000000124"
    session = Session.create(title="Clarification", created_at=created_at).model_copy(
        update={
            "status": SessionStatus.WAITING_INPUT,
            "clarification_context": ClarificationContext(
                clarification_id=clarification_id,
                tool_call_id=clarification_id,
                question="Which audience should I prioritize?",
                choices=("Operators", "Analysts"),
                context="The output format depends on the audience.",
                assistant_message="I need one decision.",
                requested_at=created_at,
            ),
        }
    )

    SQLiteProjectionStore(database_path).save_session(session)
    loaded = SQLiteProjectionStore(database_path).get_session(session.session_id)

    assert loaded == session
