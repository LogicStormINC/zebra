"""Bounded gateway execution never drains or reconciles a sibling Effect."""

from datetime import timedelta

import pytest
from agent_core.domain.effect_dispatch import (
    EffectDispatchConflictError,
    EffectDispatchStateError,
    EffectDispatchStatus,
    EffectEvidence,
)
from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import new_event_id, new_session_id, new_tool_call_id
from agent_core.domain.leases import LeaseLostError
from agent_core.ports import WorkerMutationAuthority
from agent_tools import FencedEffectToolGateway

from tests.agent_tools.test_effect_guard import _call, _CloudPayloads, _Dispatch, _fence, _Gateway


class ExactDispatch(_Dispatch):
    def __init__(self):
        super().__init__()
        self.stored = None
        self.claims = 0

    def find_by_ledger_key(self, root_session_id, *, identity):
        return self.stored

    def claim_next(self, *args, **kwargs):
        pytest.fail("strict path must not drain the queue")

    def claim_exact(self, execution_session_id, *, expected, fence, claim_ttl):
        assert expected == self.pending
        self.claims += 1
        return super().claim_next(execution_session_id, fence=fence, claim_ttl=claim_ttl)


def setup_gateway(check=lambda: None):
    dispatch = ExactDispatch()
    payloads = _CloudPayloads(dispatch)
    gateway = _Gateway()
    session = new_session_id()
    fence = _fence()
    sequence = 0

    def next_event(event_type, actor, payload):
        nonlocal sequence
        event = SessionEvent.create(
            session_id=session, sequence=sequence, event_type=event_type,
            actor=actor, payload=payload,
        )
        sequence += 1
        return event

    guarded = FencedEffectToolGateway(
        gateway, dispatch=dispatch, artifacts=None, execution_session_id=session,
        root_session_id=session, fence=fence, claim_ttl=timedelta(seconds=30),
        authority_scope="full-admitted-identity", next_event=next_event,
        accept_event=lambda event: None, ownership_check=check, effect_payloads=payloads,
        mutation_authority=lambda: WorkerMutationAuthority(
            deployment_namespace="exact-test", session_id=session, lease_fence=fence,
            expected_stream_revision=0,
        ),
    )
    return guarded, dispatch, gateway, payloads


def test_exact_uses_only_exact_claim_and_existing_cloud_publication():
    guarded, dispatch, gateway, payloads = setup_gateway()
    call = _call("dataset.snapshot.create")
    assert guarded.execute_exact(call).tool_call_id == call.tool_call_id
    assert dispatch.claims == gateway.calls == payloads.completed == 1
    assert dispatch.reconciled == dispatch.resolved == 0


@pytest.mark.parametrize("status", [
    EffectDispatchStatus.CLAIMED, EffectDispatchStatus.UNCERTAIN,
    EffectDispatchStatus.FAILED_NO_EFFECT, EffectDispatchStatus.DEAD_LETTER,
])
def test_nonpending_never_claims_or_reissues(status):
    guarded, dispatch, gateway, payloads = setup_gateway()
    call = _call("dataset.snapshot.create")
    scheduled = guarded._schedule(call)
    changes = {"status": status}
    if status is not EffectDispatchStatus.CLAIMED:
        changes.update({"evidence": EffectEvidence(reason_code="unknown")})
    if status in {EffectDispatchStatus.FAILED_NO_EFFECT, EffectDispatchStatus.DEAD_LETTER}:
        changes.update({"terminal_event_id": new_event_id()})
    dispatch.stored = scheduled.model_copy(update=changes)
    with pytest.raises(EffectDispatchStateError, match="no reissue"):
        guarded.execute_exact(call)
    assert dispatch.claims == gateway.calls == payloads.completed == 0


@pytest.mark.parametrize("fault", [
    "call", "args", "session", "root", "hash", "result", "boolean_argument",
])
def test_conflicts_refuse_before_claim_and_transport(fault):
    guarded, dispatch, gateway, payloads = setup_gateway()
    call = _call("dataset.snapshot.create")
    if fault == "boolean_argument":
        call = call.model_copy(update={"arguments": {"n": 1}})
    scheduled = guarded._schedule(call)
    if fault in {"call", "args"}:
        payloads.call = call.model_copy(update=(
            {"tool_call_id": new_tool_call_id()} if fault == "call" else {"arguments": {}}
        ))
    elif fault == "boolean_argument":
        payloads.call = call.model_copy(update={"arguments": {"n": True}})
    elif fault in {"session", "root", "hash"}:
        key = {"session": "execution_session_id", "root": "root_session_id",
               "hash": "request_hash"}[fault]
        scheduled = scheduled.model_copy(update={
            key: "f" * 64 if fault == "hash" else new_session_id()
        })
    else:
        result = gateway.execute(call).model_copy(update={"tool_call_id": new_tool_call_id()})
        gateway.calls = 0
        scheduled = scheduled.model_copy(update={
            "status": EffectDispatchStatus.SUCCEEDED, "result": result,
            "terminal_event_id": new_event_id(),
        })
    dispatch.stored = scheduled
    with pytest.raises(EffectDispatchConflictError):
        guarded.execute_exact(call)
    assert dispatch.claims == gateway.calls == payloads.completed == 0


def test_exact_replays_original_result_with_fresh_ownership_check():
    guarded, dispatch, gateway, payloads = setup_gateway()
    call = _call("dataset.snapshot.create")
    scheduled = guarded._schedule(call)
    original = gateway.execute(call)
    gateway.calls = 0
    dispatch.stored = scheduled.model_copy(update={
        "status": EffectDispatchStatus.SUCCEEDED, "result": original,
        "terminal_event_id": new_event_id(),
    })
    assert guarded.execute_exact(call) == original
    assert dispatch.claims == gateway.calls == payloads.completed == 0


@pytest.mark.parametrize("boundary", [1, 2, 3])
def test_ownership_loss_prevents_scheduling_claim_or_transport(boundary):
    checks = 0

    def check():
        nonlocal checks
        checks += 1
        if checks == boundary:
            raise LeaseLostError("STOP or stale fence")

    guarded, dispatch, gateway, payloads = setup_gateway(check)
    with pytest.raises(LeaseLostError):
        guarded.execute_exact(_call("dataset.snapshot.create"))
    assert gateway.calls == payloads.completed == 0
    if boundary < 3:
        assert dispatch.claims == 0


def test_exact_claim_race_refuses_without_transport():
    guarded, dispatch, gateway, payloads = setup_gateway()
    dispatch.claim_exact = lambda *args, **kwargs: None
    with pytest.raises(EffectDispatchStateError, match="not claimable"):
        guarded.execute_exact(_call("dataset.snapshot.create"))
    assert gateway.calls == payloads.completed == 0


@pytest.mark.parametrize("fault", [
    "failed_result", "numeric_output", "dispatch_extra", "result_extra",
    "raw_result_extra", "receipt_extra", "missing_terminal", "pending_result",
    "attempt_bool", "attempt_float", "identity_extra", "malformed_original",
])
def test_malformed_durable_replay_denied_before_claim_or_transport(fault):
    guarded, dispatch, gateway, payloads = setup_gateway()
    call = _call("dataset.snapshot.create")
    scheduled = guarded._schedule(call)
    original = gateway.execute(call)
    gateway.calls = 0
    changes = {
        "status": EffectDispatchStatus.SUCCEEDED,
        "result": original, "terminal_event_id": new_event_id(),
    }
    if fault == "failed_result":
        from agent_core.domain.tools import ToolCallStatus

        changes["result"] = original.model_copy(update={"status": ToolCallStatus.FAILED})
    elif fault == "numeric_output":
        changes["result"] = original.model_copy(update={"output": 123})
    elif fault in {"dispatch_extra", "result_extra", "identity_extra"}:
        target = {
            "dispatch_extra": scheduled, "result_extra": original,
            "identity_extra": scheduled.identity,
        }[fault]
        object.__setattr__(target, "unsupported", True)
    elif fault == "raw_result_extra":
        changes["result"] = {**original.__dict__, "unsupported": True}
    elif fault == "receipt_extra":
        changes["result"] = original.model_copy(update={"receipt": {"unsupported": True}})
    elif fault == "missing_terminal":
        changes["terminal_event_id"] = None
    elif fault == "pending_result":
        changes.update({"status": EffectDispatchStatus.PENDING, "terminal_event_id": None})
    elif fault in {"attempt_bool", "attempt_float"}:
        changes["attempt"] = True if fault == "attempt_bool" else 1.0
    elif fault == "malformed_original":
        payloads.call = call.model_copy(update={"created_at": call.created_at.replace(tzinfo=None)})
    dispatch.stored = scheduled.model_copy(update=changes)
    with pytest.raises(ValueError):
        guarded.execute_exact(call)
    assert dispatch.claims == gateway.calls == payloads.completed == 0
