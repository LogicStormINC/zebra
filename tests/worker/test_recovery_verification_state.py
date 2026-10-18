"""Offline recovery contracts: no provider, search or application database."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agent_context.conversation import _summary_message
from agent_context.materialization import _capsule_content
from agent_context.session_handoff import handoff_runtime_evidence
from agent_core.domain.context_capsule import ContextCapsule
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_message_id, new_session_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tools import ToolCall
from agent_core.harness.final_completion import _contract_verification_satisfied
from agent_core.harness.models import HarnessAttemptOutcome
from agent_core.harness.orchestration_events import continuation_metadata
from agent_storage.postgres.subagent_delegation import (
    canonical_child_terminal_summary,
    child_terminal_summary_in_transaction,
)
from zebra_agent_api.session_context_control import _capsule_from_events
from zebra_agent_worker.approved_continuation import ApprovedContinuation
from zebra_agent_worker.child_wakeup_continuation import (
    ChildResultDelivery,
    ChildWakeupContinuation,
)
from zebra_agent_worker.clarification_continuation import ClarificationContinuation
from zebra_agent_worker.continuation_dispatch import run_continuation

NOW = datetime(2026, 10, 18, tzinfo=UTC)


def state():
    return {
        "mutation_epoch": 2,
        "verified_mutation_epoch": 2,
        "mutation_resource_epochs": {"A": 1, "B": 2},
        "verified_resource_epochs": {"B": 2},
        "mutation_resource_evidence": {"A": {"commit_version": "v2"}},
        "read_fingerprint_epochs": {"read-B": 2},
        "contract_verification_prompted": True,
        "post_mutation_verification_prompted": True,
    }


def test_scope_and_deduplication_survive_shared_freeze():
    original = state()
    frozen = continuation_metadata(original)
    assert frozen == original
    assert not _contract_verification_satisfied(frozen, read_only_tools=frozenset({"read"}))
    complete = {**original, "verified_resource_epochs": {"A": 1, "B": 2}}
    assert _contract_verification_satisfied(
        continuation_metadata(complete), read_only_tools=frozenset({"read"})
    )
    global_scope = {**complete, "mutation_requires_global": True, "verified_mutation_epoch": 1}
    assert not _contract_verification_satisfied(
        continuation_metadata(global_scope), read_only_tools=frozenset({"read"})
    )
    assert "secret" not in continuation_metadata({"secret": "not orchestration state"})


def continuation(kind, metadata):
    call = ToolCall(
        tool_call_id=new_tool_call_id(), name="agent.research", arguments={}, created_at=NOW
    )
    common = dict(metadata=metadata, model_calls_used=3, tool_calls_executed=2)
    if kind == "continuation":
        completion = ModelCompletion(
            assistant_message=SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.ASSISTANT,
                content="Existing result",
                created_at=NOW,
            )
        )
        return ApprovedContinuation(completion=completion, tool_call=call, **common)
    if kind == "clarification":
        return ClarificationContinuation(
            tool_call=call,
            response="Use A",
            conversation=(),
            assistant_message="Existing result",
            **common,
        )
    return ChildWakeupContinuation(
        tool_calls=(call,),
        child_results=(ChildResultDelivery(str(new_session_id()), "failed", "Paused child"),),
        conversation=(),
        assistant_message="Existing result",
        **common,
    )


@pytest.mark.parametrize("kind", ["continuation", "clarification", "child_wakeup"])
@pytest.mark.parametrize("scope", [None, {}, {"A": True}])
def test_legacy_mutation_scope_gap_pauses_before_any_orchestrator_call(kind, scope):
    saved = {"mutation_epoch": 2, "verified_mutation_epoch": 2}
    if scope is not None:
        saved["mutation_resource_epochs"] = scope
    pending = continuation(kind, saved)
    orchestrator = Mock()
    arguments = dict(continuation=None, clarification=None)
    arguments[kind] = pending
    result = run_continuation(orchestrator, SimpleNamespace(), **arguments)
    assert result.outcome is HarnessAttemptOutcome.SUSPENDED
    assert result.metadata["delivery_assessment"]["status"] == "partial"
    assert "verification_scope_unavailable" in result.metadata["delivery_assessment"]["unmet"]
    assert result.metadata["model_calls_used"] == 3
    assert result.metadata["tool_calls_executed"] == 2
    assert "unverified" in result.metadata["assistant_message"]
    assert pending.metadata == saved
    assert orchestrator.mock_calls == []


@pytest.mark.parametrize("kind", ["continuation", "clarification", "child_wakeup"])
def test_new_scope_reaches_existing_continuation_without_losing_state(kind):
    pending = continuation(kind, continuation_metadata(state()))
    orchestrator = Mock()
    arguments = dict(continuation=None, clarification=None)
    arguments[kind] = pending
    run_continuation(orchestrator, SimpleNamespace(), **arguments)
    assert len(orchestrator.mock_calls) == 1
    assert orchestrator.mock_calls[0].kwargs["metadata"]["mutation_resource_epochs"] == {
        "A": 1,
        "B": 2,
    }
    assert orchestrator.mock_calls[0].kwargs["metadata"]["contract_verification_prompted"] is True


@pytest.mark.parametrize("passed", [False, True])
@pytest.mark.parametrize("summary", ["verifier hook skipped", "optional check unavailable"])
def test_capsule_generation_filters_skipped_but_keeps_real_results(passed, summary):
    sid = new_session_id()
    events = [
        SessionEvent.create(
            session_id=sid,
            sequence=i,
            event_type=EventType.TESTS_COMPLETED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1, "summary": label, "passed": value, "metadata": marker},
            created_at=NOW,
        )
        for i, (label, value, marker) in enumerate(
            [
                (summary, passed, {"skipped": True}),
                ("real pass", True, {}),
                ("real failure", False, {}),
            ]
        )
    ]
    original = [event.model_dump() for event in events]
    capsule = _capsule_from_events(events, created_at=NOW)
    assert capsule.tests == ("real pass", "real failure")
    assert [event.model_dump() for event in events] == original


def test_legacy_capsule_and_handoff_views_do_not_relabel_skipped():
    capsule = ContextCapsule(
        capsule_id="legacy",
        objective="task",
        immediate_next="continue",
        tests=("verifier hook skipped", "real pass"),
        source_hash="a" * 64,
        confidence=0.8,
        created_at=NOW,
    )
    original = capsule.model_dump()
    rendered, _ = _capsule_content(capsule)
    assert "verifier hook skipped" not in rendered
    assert "real pass" in rendered
    compacted = _summary_message((), capsule=capsule, max_tokens=300, created_at=NOW)
    assert "verifier hook skipped" not in compacted.content
    assert "real pass" in compacted.content
    # Existing envelopes stay immutable; only their model-facing view changes.
    envelope = SimpleNamespace(
        reason=SimpleNamespace(value="phase"),
        focus=None,
        acceptance_criteria=(),
        protected_user_constraints=(),
        decisions_and_rationale=(),
        completed_work=(),
        pending_work=(),
        rejected_approaches=(),
        permission_boundaries=(),
        touched_files=(),
        validation_results=capsule.tests,
        known_failures=(),
        open_questions=(),
        artifact_refs=(),
        completed_tool_evidence=(),
        known_omissions=(),
        immediate_next="continue",
        objective="task",
        handoff_id="h",
        source_session_id="s",
        root_session_id="s",
        target_stage_index=1,
        checksum="c",
    )
    evidence = handoff_runtime_evidence(envelope)
    assert not any("verifier hook skipped" in item for item in evidence.details)
    assert capsule.model_dump() == original


@pytest.mark.parametrize(
    "answer", ["Collected evidence", "中文证据" * 2000, ""], ids=["short", "long-cjk", "empty"]
)
def test_suspended_child_summary_keeps_reason_gaps_and_answer_within_budget(answer):
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = {
        "event_type": "session_suspended",
        "payload": {
            "reason": "verification_required",
            "metadata": {
                "assistant_message": answer,
                "delivery_assessment": {
                    "status": "partial",
                    "goal": "not part of child verification summary " * 2000,
                    "unmet": ["fresh_post_mutation_verification"],
                },
            },
        },
    }
    summary = child_terminal_summary_in_transaction(connection, "ns", new_session_id())
    assert "session_suspended" in connection.execute.call_args.args[0]
    assert "verification_required" in summary
    assert "fresh_post_mutation_verification" in summary
    if answer:
        assert answer[:8] in summary
    assert len(json.dumps(summary, sort_keys=True, separators=(",", ":")).encode()) <= 3072
    assert canonical_child_terminal_summary(summary) == summary


def test_completed_child_summary_and_missing_child_stay_compatible():
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = {
        "event_type": "session_completed",
        "payload": {"metadata": {"assistant_message": "Original completed evidence"}},
    }
    assert (
        child_terminal_summary_in_transaction(connection, "ns", new_session_id())
        == "Original completed evidence"
    )
    connection.execute.return_value.fetchone.return_value = None
    assert child_terminal_summary_in_transaction(connection, "ns", new_session_id()) is None


@pytest.mark.parametrize("status", ["suspended", "completed", "cancelled"])
def test_only_linked_suspended_child_accepts_old_generic_wakeup(status):
    from agent_core.domain.sessions import SessionStatus
    from zebra_agent_worker.execution_continuations import build_child_result_verifier

    store, projections = Mock(), Mock()
    store.get_link.return_value = SimpleNamespace(terminal_at=NOW)
    store.child_terminal_summary.return_value = "New canonical paused detail"
    projections.get_session.return_value = SimpleNamespace(status=SessionStatus(status))
    verifier = build_child_result_verifier(store, projections)
    old = canonical_child_terminal_summary(None)
    if status == "suspended":
        verifier(str(new_session_id()), "failed", old)
    else:
        with pytest.raises(ValueError):
            verifier(str(new_session_id()), "failed", old)
    with pytest.raises(ValueError):
        verifier(str(new_session_id()), "failed", "Forged result")
    store.get_link.return_value = None
    with pytest.raises(ValueError):
        verifier(str(new_session_id()), "failed", old)


@pytest.mark.parametrize("epoch", [True, False, -1, "2"])
def test_invalid_legacy_epoch_never_bypasses_scope_guard(epoch):
    from agent_core.harness.orchestration_events import continuation_verification_scope_missing

    assert continuation_verification_scope_missing({"mutation_epoch": epoch})
