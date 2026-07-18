from datetime import UTC, datetime
from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.session_projection import rebuild_session
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_storage import (
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from zebra_agent_cli.cli import execute

NOW = datetime(2026, 7, 18, tzinfo=UTC)


def test_cli_requires_confirmation_then_creates_and_reads_lineage(tmp_path: Path) -> None:
    database = tmp_path / "handoff.db"
    source = _seed_completed(database, tmp_path)
    common = [
        str(source),
        "--title",
        "Stage two",
        "--objective",
        "Continue implementation",
        "--stage-prompt",
        "Implement desktop",
        "--database",
        str(database),
    ]

    preview = execute(["handoff", "preview", *common])
    blocked = execute(["handoff", "create", *common, "--idempotency-key", "stage-two"])
    created = execute(
        [
            "handoff",
            "create",
            *common,
            "--idempotency-key",
            "stage-two",
            "--confirm",
        ]
    )
    lineage = execute(
        [
            "handoff",
            "lineage",
            str(created.payload["child_session_id"]),
            "--database",
            str(database),
        ]
    )

    assert preview.payload["status"] == "preview"
    assert blocked.payload["status"] == "confirmation_required"
    assert created.payload["status"] == "ready"
    assert len(lineage.payload["stages"]) == 2


def _seed_completed(database: Path, workspace: Path) -> SessionId:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Source", user_input="Finish stage", workspace_root=workspace, created_at=NOW
        )
    )
    events = [
        *bootstrap.events,
        SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=3,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
            created_at=NOW,
        ),
        SessionEvent.create(
            session_id=bootstrap.session.session_id,
            sequence=4,
            event_type=EventType.SESSION_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"summary": "done"},
            created_at=NOW,
        ),
    ]
    event_store = SQLiteEventStore(database)
    for event in events:
        event_store.append(event)
    SQLiteProjectionStore(database).save_session(rebuild_session(events))
    SQLiteWorkspaceProjectionStore(database).save_workspace(rebuild_workspace(events))
    return bootstrap.session.session_id
