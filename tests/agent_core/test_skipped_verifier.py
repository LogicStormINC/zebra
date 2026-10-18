from types import SimpleNamespace

from agent_core.harness.hooks import NoopVerifier
from agent_core.harness.retry_plan import build_retry_plan_hint
from agent_core.ports.context_compiler import RuntimeEvidenceInput


def test_skipped_verifier_is_not_proof_for_any_tool_status():
    for status in ("executed", "failed"):
        result = NoopVerifier().verify(
            SimpleNamespace(attempt=SimpleNamespace(number=1)), status, "unchanged tool output",
        )
        assert result.passed is False
        assert result.metadata["skipped"] is True
        assert result.metadata["tool_output"] == "unchanged tool output"


def test_skipped_verifier_is_neither_a_retry_success_nor_failure():
    for passed in (True, False):
        for metadata in ({"passed": passed}, {"passed": passed, "skipped": True}):
            hint = build_retry_plan_hint((RuntimeEvidenceInput(
                kind="verifier_summary", summary="verifier hook skipped", metadata=metadata,
            ),))
            assert hint.blockers == hint.accepted_constraints == ()


def test_skipped_event_keeps_tool_success_without_claiming_verification():
    from agent_core.domain.events import EventType
    from agent_core.harness import HarnessLoop, HarnessTask, SingleAttemptOrchestrator
    from test_sequential_tool_loop import (
        NOW,
        AllowAllPolicy,
        SequenceToolGateway,
        _completion,
        _gateway,
        _tool_call,
    )

    model = _gateway(_completion("Read.", _tool_call("files.read", {}, "one-read")),
                     _completion("Read result."))
    result = HarnessLoop().run(
        HarnessTask(title="Read", user_input="Explain this text.", max_model_calls=2),
        SingleAttemptOrchestrator(model, AllowAllPolicy(), SequenceToolGateway(),
                                  synthesize_tool_results=True).run, created_at=NOW,
    )
    verification = next(e for e in result.events if e.event_type is EventType.TESTS_COMPLETED)
    assert verification.payload["passed"] is False
    assert verification.payload["metadata"]["skipped"] is True
    assert result.attempt_result.metadata["tool_status"] == "executed"
    assert result.attempt_result.metadata["verification_passed"] is False
    assert result.run_result.model_calls_used == 2


def test_explicit_skipped_with_other_summary_never_becomes_retry_evidence():
    for passed in (False, True):
        hint = build_retry_plan_hint((RuntimeEvidenceInput(
            kind="verifier_summary", summary="optional check unavailable",
            metadata={"passed": passed, "skipped": True},
        ),))
        assert hint.blockers == hint.accepted_constraints == ()


def test_explicit_skipped_is_not_contract_proof_but_independent_evidence_counts():
    from agent_core.harness.final_completion import _contract_verification_satisfied

    skipped = {"verification_summary": "optional check unavailable",
               "verification_passed": True, "verification_metadata": {"skipped": True}}
    assert not _contract_verification_satisfied(skipped, read_only_tools=frozenset())
    assert _contract_verification_satisfied(
        {**skipped, "tool_metadata": {"postcondition_met": True}},
        read_only_tools=frozenset(),
    )
    assert _contract_verification_satisfied(
        {**skipped, "mutation_epoch": 2, "verified_mutation_epoch": 2},
        read_only_tools=frozenset(),
    )
    assert not _contract_verification_satisfied(
        {**skipped, "mutation_epoch": 2, "verified_mutation_epoch": 1},
        read_only_tools=frozenset(),
    )
