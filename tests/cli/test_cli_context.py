from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_cli.cli import execute


def test_cli_context_compact_and_inspect(tmp_path: Path) -> None:
    database = tmp_path / "sessions.sqlite"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="CLI context",
            user_input="Keep the decision trail.",
            workspace_root=tmp_path.resolve(),
        )
    )
    store = SQLiteEventStore(database)
    for event in bootstrap.events:
        store.append(event)
    SQLiteProjectionStore(database).save_session(bootstrap.session)
    session_id = str(bootstrap.session.session_id)

    compacted = execute(
        ["context", "compact", session_id, "--database", str(database)]
    )
    inspected = execute(
        ["context", "inspect", session_id, "--database", str(database)]
    )

    assert compacted.command == "context"
    assert compacted.payload["action"] == "compact"
    assert compacted.payload["status"] == "compacted"
    assert inspected.command == "context"
    assert inspected.payload["action"] == "inspect"
    assert inspected.payload["compaction_count"] == 1


def test_cli_context_preview_focus_and_recover(tmp_path: Path) -> None:
    database = tmp_path / "sessions.sqlite"
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="CLI context lifecycle",
            user_input="Preserve the accepted API contract.",
            workspace_root=tmp_path.resolve(),
        )
    )
    store = SQLiteEventStore(database)
    for event in bootstrap.events:
        store.append(event)
    SQLiteProjectionStore(database).save_session(bootstrap.session)
    session_id = str(bootstrap.session.session_id)

    preview = execute(
        [
            "context",
            "compact",
            session_id,
            "--focus",
            "API contract",
            "--preview",
            "--database",
            str(database),
        ]
    )
    assert preview.payload["status"] == "preview"
    compacted = execute(
        ["context", "compact", session_id, "--database", str(database)]
    )
    capsule_id = compacted.payload["capsule"]["capsule_id"]
    recovered = execute(
        [
            "context",
            "recover",
            session_id,
            capsule_id,
            "--database",
            str(database),
        ]
    )
    assert recovered.payload["status"] == "recovered"
