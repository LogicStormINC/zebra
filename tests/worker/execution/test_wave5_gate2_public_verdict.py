"""Wave 5 Gate 2 public-boundary tests (ZNX-WAVE5-OUTER-ATTEMPTS-01).

The public projection must sanitize the terminal coverage verdict: an exact
five-field safe object rebuilt from validated counts and a fixed message,
never the source dict or source message. Malformed verdicts (extra/private
keys, wrong types, bool-as-int, negative or inconsistent counts, status
mismatch) fail closed by omitting the verdict.
"""

from pathlib import Path

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.tool_profiles import ToolProfile
from agent_storage import (
    SQLiteAgentTaskStore,
    SQLiteEventStore,
    SQLiteProjectionStore,
    SQLiteWorkspaceProjectionStore,
)
from worker_execution_support import _created_at
from zebra_agent_worker import SessionRecoveryService


def _seed_session(database_path: Path, workspace_root: Path):
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Queued coverage task",
            user_input="Complete the analysis.",
            workspace_root=workspace_root.resolve(),
            tool_profile=ToolProfile.CODING,
            max_attempts=2,
            max_corrections_per_attempt=1,
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


_POISONED_VERDICTS = (
    (
        "private_keys_and_attacker_message",
        {
            "status": "missing",
            "required_count": 1,
            "satisfied_count": 0,
            "missing_count": 1,
            "message": "ATTACKER-CONTROLLED MESSAGE",
            "requirement_ids": ["authoritative_financial"],
            "resource_manifest_digest": "sha256:" + "f" * 64,
            "internal_diagnostics": "coverage-report:attempt-1",
        },
        {
            "status": "missing",
            "required_count": 1,
            "satisfied_count": 0,
            "missing_count": 1,
            "message": (
                "Required evidence coverage is not satisfied; the task cannot "
                "complete without trusted evidence."
            ),
        },
    ),
    (
        "private_keys_complete",
        {
            "status": "complete",
            "required_count": 1,
            "satisfied_count": 1,
            "missing_count": 0,
            "message": "ATTACKER-CONTROLLED MESSAGE",
            "requirement_ids": ["authoritative_financial"],
        },
        {
            "status": "complete",
            "required_count": 1,
            "satisfied_count": 1,
            "missing_count": 0,
            "message": "Required evidence coverage is satisfied.",
        },
    ),
    (
        "wrong_types",
        {
            "status": "missing",
            "required_count": "1",
            "satisfied_count": 0,
            "missing_count": 1,
            "message": "x",
        },
        None,
    ),
    (
        "bool_as_int",
        {
            "status": "missing",
            "required_count": True,
            "satisfied_count": 0,
            "missing_count": 1,
            "message": "x",
        },
        None,
    ),
    (
        "negative_counts",
        {
            "status": "missing",
            "required_count": 1,
            "satisfied_count": 0,
            "missing_count": -1,
            "message": "x",
        },
        None,
    ),
    (
        "inconsistent_counts",
        {
            "status": "missing",
            "required_count": 2,
            "satisfied_count": 1,
            "missing_count": 0,
            "message": "x",
        },
        None,
    ),
    (
        "status_mismatch",
        {
            "status": "missing",
            "required_count": 1,
            "satisfied_count": 1,
            "missing_count": 0,
            "message": "x",
        },
        None,
    ),
)


@pytest.mark.parametrize(
    "terminal_type",
    (EventType.SESSION_COMPLETED, EventType.SESSION_FAILED),
)
@pytest.mark.parametrize(
    ("case_name", "raw_verdict", "expected_verdict"),
    _POISONED_VERDICTS,
)
def test_public_projection_sanitizes_coverage_verdict(
    tmp_path: Path,
    terminal_type: EventType,
    case_name: str,
    raw_verdict: dict[str, object],
    expected_verdict: dict[str, object] | None,
) -> None:
    from agent_core.application.public_conversation import project_public_conversation

    database_path = tmp_path / f"wave5-p1-1-{terminal_type.value}-{case_name}.db"
    bootstrap = _seed_session(database_path, tmp_path)
    session_id = bootstrap.session.session_id
    event_store = SQLiteEventStore(database_path)
    terminal = SessionEvent.create(
        session_id=session_id,
        sequence=3,
        event_type=terminal_type,
        actor=EventActor.HARNESS,
        payload={
            "attempt_number": 1,
            "summary": "coverage terminal",
            "coverage_verdict": raw_verdict,
            "retryable": False,
        },
        created_at=_created_at(),
    )
    event_store.append(terminal)
    task_store = SQLiteAgentTaskStore(database_path)
    task = task_store.ensure_for_session(session_id)
    task_events = task_store.read_events(task.task_id, -1)

    projection = project_public_conversation(task.task_id, task_events)
    if terminal_type is EventType.SESSION_FAILED:
        items = [item for item in projection.items if item.role == "failure"]
    else:
        items = [
            item
            for item in projection.items
            if item.role == "progress_summary" and item.state == "completed"
        ]
    assert len(items) == 1
    if expected_verdict is None:
        assert "coverage_verdict" not in items[0].data
        return
    verdict = items[0].data["coverage_verdict"]
    assert verdict == expected_verdict
    assert set(verdict) == {
        "status",
        "required_count",
        "satisfied_count",
        "missing_count",
        "message",
    }
    assert "requirement_ids" not in items[0].data
    assert "resource_manifest_digest" not in items[0].data
    assert "internal_diagnostics" not in items[0].data
