from datetime import UTC, datetime

from agent_core.domain.identifiers import new_session_id
from agent_core.domain.sessions import Session, SessionStatus
from agent_core.harness import (
    HarnessAttempt,
    HarnessContext,
    HarnessTask,
    NoopPlanner,
    build_retry_plan_hint,
)
from agent_core.ports.context_compiler import RuntimeEvidenceInput


def test_build_retry_plan_hint_groups_structured_runtime_evidence() -> None:
    hint = build_retry_plan_hint(
        (
            RuntimeEvidenceInput(
                kind="planner_summary",
                summary="Inspect failing smoke test.",
            ),
            RuntimeEvidenceInput(
                kind="verifier_summary",
                summary="Smoke test still fails.",
                metadata={"passed": False},
            ),
            RuntimeEvidenceInput(
                kind="verifier_summary",
                summary="Existing import path remains valid.",
                metadata={"passed": True},
            ),
            RuntimeEvidenceInput(kind="tool_status", summary="failed"),
            RuntimeEvidenceInput(
                kind="tool_output_summary",
                summary="tests.run: assertion failed",
                artifact_uri="artifact://tests/1",
            ),
        )
    )

    assert (
        hint.summary
        == "retry should address verifier or tool failures before repeating prior steps"
    )
    assert hint.focus == ("Inspect failing smoke test.",)
    assert hint.blockers == ("Smoke test still fails.", "previous tool status: failed")
    assert hint.accepted_constraints == ("Existing import path remains valid.",)
    assert hint.prior_tool_outputs == ("tests.run: assertion failed",)


def test_noop_planner_uses_retry_plan_hint_on_retry_attempt() -> None:
    planner = NoopPlanner()
    context = HarnessContext(
        task=HarnessTask(
            title="Fix retry",
            user_input="Use prior evidence.",
            runtime_evidence=(
                RuntimeEvidenceInput(
                    kind="planner_summary",
                    summary="Check the failing branch.",
                ),
                RuntimeEvidenceInput(
                    kind="verifier_summary",
                    summary="Regression test failed.",
                    metadata={"passed": False},
                ),
            ),
        ),
        session=Session(
            session_id=new_session_id(),
            title="Retry",
            status=SessionStatus.RUNNING,
            created_at=datetime(2026, 6, 22, 14, 0, tzinfo=UTC),
            updated_at=datetime(2026, 6, 22, 14, 0, tzinfo=UTC),
        ),
        attempt=HarnessAttempt(
            number=2,
            started_at=datetime(2026, 6, 22, 14, 1, tzinfo=UTC),
        ),
    )

    result = planner.plan(context)

    assert result.summary == (
        "retry should address verifier or tool failures before repeating prior steps"
    )
    assert result.metadata["attempt_number"] == 2
    assert result.metadata["retry_focus"] == ("Check the failing branch.",)
    assert result.metadata["retry_blockers"] == ("Regression test failed.",)
