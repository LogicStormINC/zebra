"""Shared fixtures for the Wave 5 Gate 1 correction suites."""

from __future__ import annotations

from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.events import EventType
from agent_core.domain.tool_profiles import ToolProfile
from agent_storage import (
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from zebra_agent_worker import SessionRecoveryService


def _seed(database_path: Path, workspace_root: Path, *, max_attempts: int = 2):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Queued worker task",
            user_input="Continue the queued task.",
            workspace_root=workspace_root.resolve(),
            tool_profile=ToolProfile.CODING,
            max_attempts=max_attempts,
        )
    )
    event_store = SQLiteEventStore(database_path)
    for event in bootstrap.events:
        event_store.append(event)
    SQLiteProjectionStore(database_path).save_session(bootstrap.session)
    SessionRecoveryService(
        event_store,
        SQLiteProjectionStore(database_path),
        SQLiteWorkspaceProjectionStore(database_path),
    ).recover_session(bootstrap.session.session_id)
    return bootstrap


class _ExplodingGateway:
    provider = "test"
    model_name = "test-model"

    def complete(self, messages, *, tools=()):
        raise RuntimeError("provider transport exploded")

    def complete_stream(self, messages, *, tools=(), on_text_delta=None):
        raise RuntimeError("provider transport exploded")


class _RecordingGateway:
    provider = "test"
    model_name = "test-model"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete(self, messages, *, tools=()):
        self.calls.append("complete")
        return None

    def complete_stream(self, messages, *, tools=(), on_text_delta=None):
        self.calls.append("complete_stream")
        return None


def _attempt_started(events):
    return [event for event in events if event.event_type is EventType.HARNESS_ATTEMPT_STARTED]


def _outcomes(events):
    return [event for event in events if event.event_type is EventType.ATTEMPT_OUTCOME_RECORDED]
