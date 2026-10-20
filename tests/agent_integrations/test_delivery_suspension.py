from agent_core.domain.events import EventType
from agent_core.domain.identifiers import new_session_id
from agent_integrations.ag_ui.interrupts import project_budget_suspension_event

from tests.agent_integrations.test_ag_ui_projection import _event, _identity


def test_delivery_suspension_is_a_truthful_interrupt_not_execution_failure():
    session = new_session_id()
    event = _event(
        session,
        1,
        EventType.SESSION_SUSPENDED,
        {
            "reason": "delivery_requirements_unmet",
            "metadata": {
                "delivery_assessment": {
                    "status": "blocked",
                    "unmet": ["citation_uses_exact_collected_url"],
                },
            },
        },
    )
    frames = project_budget_suspension_event(event, _identity(session), 1)
    assert len(frames) == 2
    snapshot, finish = frames
    assert snapshot.snapshot["session"]["status"] == "suspended"
    assert finish.outcome.type == "interrupt"
    assert finish.outcome.interrupts[0].reason == "delivery_requirements_unmet"
