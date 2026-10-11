"""Initializer scope/floor guards; scratch Events are not provider acceptance."""

import json
from hashlib import sha256
from io import StringIO
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from agent_core.contracts.session_commands import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_storage.postgres.events import PostgresEventStore
from agent_storage.postgres.task_lineage import PostgresAgentTaskConflictError
from joint_commit_identity import initialize_identity, main
from joint_commit_visibility import CommitVisibilityProbe
from psycopg.conninfo import conninfo_to_dict

from tests.agent_storage.test_postgres_command_wakeup import (
    NAMESPACE,
    _seed,
    dsn,  # noqa: F401
    postgres_dsn,  # noqa: F401
)


@pytest.mark.parametrize(
    "admission",
    [
        {},
        {"conversation_key": "c", "run_id": "r", "turn_id": "bad"},
        {"conversation_key": "c", "run_id": "r", "turn_id": str(uuid4()), "task_id": str(uuid4())},
    ],
)
def test_exact_coordinates_required_before_any_lookup(admission):
    with pytest.raises((ValueError, TypeError)):
        initialize_identity(None, admission)


def test_cli_private_inputs_and_sanitized_failure(monkeypatch, tmp_path):
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps({"TRENCH_E2E_BFF_URL": "http://localhost", "secret": "SECRET"}))
    path.chmod(0o600)
    request = dict(conversation_key="c", run_id="r", turn_id=str(uuid4()))
    monkeypatch.setattr("sys.argv", ["identity", "--inputs", str(path)])
    monkeypatch.setattr("support.load_config", lambda *args: None)
    # This module imports the loader directly; no native read for this CLI guard.
    monkeypatch.setattr("joint_commit_identity.load_config", lambda *args: None)
    monkeypatch.setattr(
        "joint_commit_identity.initialize_identity",
        lambda *_: {"status": "preparing", "reason": "canonical_run_not_visible", **request},
    )
    output = StringIO()
    monkeypatch.setattr("sys.stdout", output)
    monkeypatch.setattr("sys.stdin", StringIO(json.dumps(request) + "\n"))
    assert main() == 0
    assert json.loads(output.getvalue())["status"] == "preparing"
    output.seek(0)
    output.truncate()
    path.chmod(0o644)
    assert main() == 2
    assert "SECRET" not in output.getvalue()


def test_native_initializer_uses_exact_run_anchor_not_current_highwater(dsn, monkeypatch):  # noqa: F811
    session = _seed(dsn)
    request = dict(conversation_key="conversation", run_id="exact-run", turn_id=str(uuid4()))
    endpoint = "http://localhost/tasks"
    config = SimpleNamespace(
        runtime_tasks_url=endpoint,
        user_id="user-a",
        workspace_id="workspace-a",
        trench_database_dsn=dsn,
        zebra_database_dsn=dsn,
    )
    full_key = "trench_ai::user-a::workspace-a::conversation"
    with psycopg.connect(dsn) as c:
        task, floor = c.execute(
            "SELECT task_id,MAX(task_sequence) FROM session_events "
            "WHERE deployment_namespace=%s AND session_id=%s GROUP BY task_id",
            (NAMESPACE, session.session_id),
        ).fetchone()
        c.execute(
            "CREATE TABLE trench_ai_product_conversations (key TEXT PRIMARY KEY, "
            "user_id TEXT,workspace_id TEXT,zebra_task_id TEXT,deleted_at_ms BIGINT)"
        )
        c.execute(
            "CREATE TABLE trench_ai_task_bindings (runtime_domain TEXT,task_id TEXT,"
            "host_thread TEXT,conversation_key TEXT,user_id TEXT,workspace_id TEXT,"
            "PRIMARY KEY(runtime_domain,task_id))"
        )
        c.execute(
            "CREATE TABLE trench_ai_turns (turn_id TEXT PRIMARY KEY,run_id TEXT,"
            "conversation_key TEXT,user_id TEXT,workspace_id TEXT)"
        )
        c.execute(
            "INSERT INTO trench_ai_product_conversations "
            "VALUES (%s,'user-a','workspace-a',%s,NULL)",
            (full_key, str(task)),
        )
        c.execute(
            "INSERT INTO trench_ai_task_bindings VALUES (%s,%s,%s,%s,'user-a','workspace-a')",
            (
                sha256(endpoint.encode()).hexdigest(),
                str(task),
                "trench-bootstrap-" + uuid4().hex,
                full_key,
            ),
        )
        c.execute(
            "INSERT INTO trench_ai_turns VALUES (%s,%s,%s,'user-a','workspace-a')",
            (request["turn_id"], request["run_id"], full_key),
        )
    monkeypatch.setattr(
        "joint_commit_identity.joint_preflight", lambda _: {"namespace_id": NAMESPACE}
    )
    monkeypatch.setattr("isolation.validate_base", lambda *args, **kwargs: {})
    original_connect = psycopg.connect

    def isolated_connect(conninfo, *args, **kwargs):
        # support.task_binding replaces options for its read-only budget. Keep this
        # fixture's search_path as well; real QA uses separate databases, not schemas.
        kwargs["options"] = " ".join(
            filter(None, (conninfo_to_dict(conninfo).get("options"), kwargs.get("options")))
        )
        return original_connect(conninfo, *args, **kwargs)

    monkeypatch.setattr(psycopg, "connect", isolated_connect)
    pending = initialize_identity(config, request)
    assert pending["status"] == "preparing" and "after_sequence" not in pending
    events = PostgresEventStore(dsn, deployment_namespace=NAMESPACE)
    command = SessionCommand(
        session_id=session.session_id,
        kind=SessionCommandKind.RUN,
        expected_revision=floor,
        idempotency_key="identity",
        payload={"run_id": request["run_id"]},
    )
    anchor = SessionEvent.create(
        session_id=session.session_id,
        sequence=floor + 1,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=command.event_payload(),
    )
    events.append(anchor)
    output = SessionEvent.create(
        session_id=session.session_id,
        sequence=anchor.sequence + 1,
        event_type=EventType.PUBLIC_OUTPUT,
        actor=EventActor.SYSTEM,
        payload=dict(
            schema_version=1,
            attempt_number=1,
            output_id="out:identity",
            kind="commentary",
            phase="evidence",
            origin="system",
            content="Fixture visibility.",
            status="complete",
        ),
    )
    events.append(output)
    identity = initialize_identity(config, request)
    assert identity["task_id"] == str(task) and identity["after_sequence"] == floor
    assert identity["anchor_event_id"] == str(anchor.event_id)
    assert identity["absence_proof"] is False
    probe = CommitVisibilityProbe(
        dsn,
        deployment_namespace=NAMESPACE,
        task_id=str(task),
        run_id=request["run_id"],
        turn_id=request["turn_id"],
        after_sequence=identity["after_sequence"],
    )
    assert probe.poll()["records"][0]["status"] == "left_censored"
    assert probe.report()["records"][0]["event_id"] == str(output.event_id)
    for changed in (
        {**request, "run_id": "other-run"},
        {**request, "turn_id": str(uuid4())},
        {**request, "conversation_key": "other"},
    ):
        with pytest.raises(ValueError, match="admitted_turn_run_mismatch"):
            initialize_identity(config, changed)
    monkeypatch.setattr(
        "joint_commit_identity.joint_preflight", lambda _: {"namespace_id": "other"}
    )
    with pytest.raises(PostgresAgentTaskConflictError):
        initialize_identity(config, request)  # No fallback to the unscoped Task.
