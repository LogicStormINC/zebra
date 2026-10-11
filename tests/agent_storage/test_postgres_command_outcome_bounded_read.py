"""Native observer outcome lookup cannot hydrate command/history bodies."""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from tests.agent_storage.test_postgres_command_wakeup_outcome import _read, _setup
from tests.agent_storage.test_postgres_command_wakeup_outcome import dsn as _dsn
from tests.agent_storage.test_postgres_command_wakeup_outcome import postgres_dsn as _postgres_dsn

dsn = _dsn
postgres_dsn = _postgres_dsn


def test_outcome_uses_native_budget_and_scalar_canonical_identity(
    dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event, context = _setup(dsn)  # type: ignore[no-untyped-call]
    with psycopg.connect(dsn) as writer:
        writer.execute("UPDATE session_command_pending SET status='dead'")
    execute = psycopg.Cursor.execute
    queries: list[str] = []
    connections: set[str] = set()

    def observe(
        cursor: psycopg.Cursor[Any],
        query: Any,
        params: Any = None,
        **kwargs: Any,
    ) -> psycopg.Cursor[Any]:
        statement = " ".join(str(query).split())
        queries.append(statement)
        connections.add(type(cursor.connection).__name__)
        if "session_events" in statement:
            assert "event.*" not in statement
            assert "SELECT *" not in statement
            if "payload" in statement:
                # One bounded scalar from the exact canonical anchor is not a
                # historical body read. Keep source command identity validation.
                assert "payload->>'command_id' AS command_id" in statement
                assert (
                    "task_sequence=%s AND event_id=%s AND session_id=%s AND sequence=%s"
                    in statement
                )
                assert params[-3:] == (event.event_id, event.session_id, event.sequence)
        return execute(cursor, query, params, **kwargs)

    monkeypatch.setattr(psycopg.Cursor, "execute", observe)
    assert _read(dsn, event, context) == "command_delivery_failed"  # type: ignore[no-untyped-call]
    assert connections == {"TaskIoConnection"}
    assert any("replay_run_id=%s" in query and "LIMIT 2" in query for query in queries)
    assert len([query for query in queries if "payload" in query]) == 1
