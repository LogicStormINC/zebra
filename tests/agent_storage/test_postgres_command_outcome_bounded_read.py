"""Native observer outcome lookup cannot hydrate command/history bodies."""

from __future__ import annotations

import re
from typing import Any

import psycopg
import pytest

from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE
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
        anchor = writer.execute(
            "SELECT task_id,task_sequence FROM session_events "
            "WHERE deployment_namespace=%s AND event_id=%s",
            (NAMESPACE, event.event_id),
        ).fetchone()
        assert anchor is not None
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
            for wildcard in re.finditer(r"\bSELECT\s+\*\s+FROM\s+", statement, re.I):
                source = statement[wildcard.end():]
                assert re.match(
                    r"(?:executable|control|anchor|stop)\s*(?:UNION\b|\)|$)", source, re.I,
                ) or (
                    wildcard.start() == 0 and source.startswith("(WITH args AS ")
                    and statement.endswith(") metadata") and "payload" not in statement
                )
            for projection in re.findall(
                r"SELECT\s+((?:(?!SELECT).)*?)\s+FROM\s+session_events\b", statement, re.I,
            ):
                assert not re.search(r"(?:^|,)\s*(?:\w+\.)?\*(?:\s|,|$)", projection)
            for alias in re.findall(
                r"(?:FROM|JOIN)\s+session_events(?:\s+AS)?\s+(\w+)", statement, re.I,
            ):
                assert not re.search(rf"\b{alias}\s*\.\s*\*", statement)
            if "payload" in statement:
                assert len(re.findall(r"\bpayload\b", statement, re.I)) == 1
                # One bounded scalar from the exact canonical anchor is not a
                # historical body read. Keep source command identity validation.
                assert "payload->>'command_id' AS command_id" in statement
                assert (
                    "%s::text ns,%s::uuid tid,%s::bigint position,"
                    "%s::uuid eid,%s::uuid sid,%s::bigint sequence"
                ) in statement
                for column, argument in (
                    ("deployment_namespace", "ns"), ("task_id", "tid"),
                    ("task_sequence", "position"), ("event_id", "eid"),
                    ("session_id", "sid"), ("sequence", "sequence"),
                ):
                    assert f"{column}=(SELECT {argument} FROM args)" in statement
                assert params[:6] == (
                    NAMESPACE, anchor[0], anchor[1],
                    event.event_id, event.session_id, event.sequence,
                )
        return execute(cursor, query, params, **kwargs)

    monkeypatch.setattr(psycopg.Cursor, "execute", observe)
    assert _read(dsn, event, context) == "command_delivery_failed"  # type: ignore[no-untyped-call]
    assert connections == {"TaskIoConnection"}
    assert any(
        "replay_run_id=(SELECT rid FROM args)" in query and "LIMIT 2" in query
        and "payload" not in query for query in queries
    )
    assert len([query for query in queries if "payload" in query]) == 1
