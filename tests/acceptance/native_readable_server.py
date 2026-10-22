"""Readable command fixture helpers: existing SQLite command authority and real Worker Context."""

from pathlib import Path

from agent_context.adapter import LocalContextCompiler
from agent_core.domain.events import EventType
from agent_storage import SQLiteEventStore
from zebra_agent_worker.task_recovery import recover_client_state_evidence

from tests.api.test_agui_command_routes import _seed_ready_session


def prepare_readable_fixture(folder: Path):
    return _seed_ready_session(folder)


def readable_report(database_path, task_id, folder: Path):
    # Reopen durable adapters, never report from the BFF request or an in-memory cache.
    events = SQLiteEventStore(database_path).list_for_session(task_id)
    commands = [
        event
        for event in events
        if event.event_type is EventType.SESSION_COMMAND_ACCEPTED
        and isinstance(event.payload.get("payload", {}).get("client"), dict)
    ]
    evidence = recover_client_state_evidence(events)
    prompt = LocalContextCompiler().build_system_prompt(
        task_input="Inspect the registered page state",
        workspace_root=folder,
        max_tokens=4000,
        runtime_evidence=() if evidence is None else (evidence,),
    )
    return {
        "commands": len(commands),
        "revision": events[-1].sequence,
        "states": [event.payload["payload"]["client"]["state_snapshot"] for event in commands],
        "lastState": None if evidence is None else evidence.metadata["state"],
        "digest": None if evidence is None else evidence.metadata["state_digest"],
        "prompt": prompt,
    }
