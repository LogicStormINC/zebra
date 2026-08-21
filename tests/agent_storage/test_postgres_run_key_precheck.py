"""Run-key pre-check adversarial regression.

A durable accepted event whose command_id is not a UUID — even with a
self-consistent fingerprint — must fail closed: the pre-check parses
through the CORE contract, so direct store corruption (raw SQL insert
bypassing the validating append) cannot be rebuilt into an accepted
body.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import zebra_agent_api.api_command_mixin as command_mixin
from agent_core.domain.identifiers import SessionId
from agent_storage.runtime_composition import CloudCompositionSettings
from psycopg import connect
from zebra_agent_api.factory import create_app

from tests.agent_storage.test_postgres_default_chain_e2e import (
    PARENT_PROMPT,
    _settings,
)


def test_run_key_held_by_malformed_command_id_conflicts(
    postgres_dsn: str,
    cloud_composition: CloudCompositionSettings,
    namespace: str,
    tmp_path: Path,
) -> None:
    """A durable accepted event whose command_id is not a UUID — with an
    otherwise self-consistent fingerprint — must NOT be rebuilt into a
    202 accepted body. The pre-check parses through the core contract
    (SessionCommandAcceptedPayload + SessionCommand fingerprint), so any
    malformation fails closed into idempotency_conflict."""


    import psycopg

    cloud = CloudCompositionSettings(
        dsn=postgres_dsn,
        deployment_namespace=namespace,
        memory_cursor_signing_key=cloud_composition.memory_cursor_signing_key,
        artifact_objects=cloud_composition.artifact_objects,
        history_scope=cloud_composition.history_scope,
        continuation_scope=cloud_composition.continuation_scope,
    )
    settings = _settings("http://127.0.0.1:9", postgres_dsn)
    workspace_root = tmp_path / "workspace-malformed"
    workspace_root.mkdir()
    app = create_app(
        database_path=tmp_path / "unused.sqlite",
        settings=settings,
        cloud_composition=cloud,
    )
    payload = {
        "title": "malformed-e2e",
        "prompt": PARENT_PROMPT,
        "workspace": str(workspace_root),
        "execute": True,
    }
    # Crash after admission, before the run command submission.
    original_submit = command_mixin.submit_session_command

    def crashing_submit(*args, **kwargs):
        raise RuntimeError("simulated crash after admission")

    command_mixin.submit_session_command = crashing_submit
    try:
        with pytest.raises(RuntimeError, match="simulated crash"):
            app.create_session(payload, idempotency_key="e2e-malformed-1")
    finally:
        command_mixin.submit_session_command = original_submit
    with connect(postgres_dsn) as connection:
        row = connection.execute(
            """
            SELECT session_id FROM session_streams
            WHERE deployment_namespace = %s
            """,
            (namespace,),
        ).fetchone()
    session_id = str(row[0])
    stream_events = app.stores.events.list_for_session(SessionId(UUID(session_id)))
    expected_revision = stream_events[-1].sequence
    # Build a FULLY legitimate command payload through the core
    # contract, then corrupt exactly ONE field — command_id — so it is
    # the single fault variable. The core fingerprint deliberately
    # excludes command_id, which is exactly the hole this test pins;
    # deriving the payload from event_payload() keeps it correct even
    # if the core algorithm evolves.
    from agent_core.contracts import SessionCommand, SessionCommandKind

    command = SessionCommand(
        command_id=uuid4(),
        session_id=SessionId(UUID(session_id)),
        kind=SessionCommandKind.RUN,
        expected_revision=expected_revision,
        idempotency_key="e2e-malformed-1:run",
        payload={},
    )
    event_payload = command.event_payload()
    event_payload["command_id"] = "not-a-uuid"
    # Bypass the validating append path with a raw insert — the threat
    # model is direct store corruption, which the API layer never sees.
    with connect(postgres_dsn) as connection:
        connection.execute(
            """
            UPDATE session_streams SET current_version = %s
            WHERE deployment_namespace = %s AND session_id = %s
            """,
            (expected_revision + 1, namespace, session_id),
        )
        connection.execute(
            """
            INSERT INTO session_events (
                deployment_namespace, event_id, session_id, sequence,
                event_type, payload, actor, created_at, idempotency_key
            ) VALUES (%s, %s, %s, %s, 'session_command_accepted', %s, 'user', %s, %s)
            """,
            (
                namespace,
                str(uuid4()),
                session_id,
                expected_revision + 1,
                psycopg.types.json.Json(event_payload),
                datetime.now(UTC),
                "e2e-malformed-1:run",
            ),
        )

    replayed = app.create_session(payload, idempotency_key="e2e-malformed-1")
    assert replayed.status_code == 409, replayed.body
    assert replayed.body["status"] == "idempotency_conflict"
    assert replayed.body.get("command") is None

    with connect(postgres_dsn) as connection:
        runs = connection.execute(
            """
            SELECT count(*) FROM session_events
            WHERE deployment_namespace = %s
                AND event_type = 'session_command_accepted'
                AND payload ->> 'kind' = 'run'
                AND payload ->> 'command_id' <> 'not-a-uuid'
            """,
            (namespace,),
        ).fetchone()
    assert int(runs[0]) == 0, "no accepted run body may be fabricated"
