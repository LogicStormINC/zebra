from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.clarifications import ClarificationContext
from agent_core.domain.sessions import Session, SessionStatus
from agent_storage import SQLiteProjectionStore
from zebra_agent_api import create_app
from zebra_agent_cli.cli import execute


def test_api_and_cli_expose_only_operator_clarification_fields(tmp_path: Path) -> None:
    database_path = tmp_path / "clarification.sqlite"
    requested_at = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
    clarification_id = "00000000-0000-0000-0000-000000000124"
    session = Session.create(title="Clarification", created_at=requested_at).model_copy(
        update={
            "status": SessionStatus.WAITING_INPUT,
            "clarification_context": ClarificationContext(
                clarification_id=clarification_id,
                tool_call_id=clarification_id,
                provider_call_id="provider-secret",
                question="Which audience should I prioritize?",
                choices=("Operators", "Analysts"),
                context="The output format depends on the audience.",
                assistant_message="Internal protocol message",
                requested_at=requested_at,
            ),
        }
    )
    SQLiteProjectionStore(database_path).save_session(session)
    expected = {
        "clarification_id": clarification_id,
        "question": "Which audience should I prioritize?",
        "choices": ["Operators", "Analysts"],
        "context": "The output format depends on the audience.",
        "requested_at": requested_at.isoformat(),
    }

    api_context = create_app(database_path).get_session(str(session.session_id)).body[
        "clarification_context"
    ]
    cli_context = execute(
        ["inspect", str(session.session_id), "--database", str(database_path)]
    ).payload["clarification_context"]

    assert api_context == expected
    assert cli_context == expected
