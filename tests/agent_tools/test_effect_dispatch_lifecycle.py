"""Dispatch admission failures must not be confused with unknown provider writes."""

from asyncio import CancelledError
from datetime import timedelta

import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id
from agent_core.domain.leases import LeaseLostError
from agent_storage import SQLiteArtifactPayloadStore
from agent_tools import FencedEffectToolGateway

from tests.agent_tools.test_effect_guard import _call, _Dispatch, _fence, _Gateway


@pytest.mark.parametrize(
    "failure", ["lease_loss", "callback_error", "provider_error", "provider_cancel"]
)
@pytest.mark.parametrize("terminal_rejected", [False, True, "cancelled"])
def test_start_callback_and_provider_exceptions_keep_dispatch_evidence(
    tmp_path, monkeypatch, failure, terminal_rejected
) -> None:
    gateway = _Gateway()
    dispatch = _Dispatch()
    accepted = []
    evidence = []
    terminal_attempts = []
    session_id = new_session_id()
    owned = True

    def require_owned():
        if not owned:
            raise LeaseLostError("callback lost lease")

    def started(_call_id):
        nonlocal owned
        if failure == "lease_loss":
            owned = False
        elif failure == "callback_error":
            raise RuntimeError("start observer failed")

    def provider(call):
        if failure in {"provider_error", "provider_cancel"}:
            gateway.calls += 1
            if failure == "provider_cancel":
                raise CancelledError("provider cancelled")
            raise TimeoutError("provider outcome unknown")
        return original_execute(call)

    original_execute = gateway.execute
    monkeypatch.setattr(gateway, "execute", provider)

    def terminal(method):
        def commit(claim, *, evidence, terminal_event):
            terminal_attempts.append(evidence.reason_code)
            if terminal_rejected == "cancelled":
                raise CancelledError("terminal commit cancelled")
            if terminal_rejected:
                raise LeaseLostError("terminal fence rejected")
            return method(claim, evidence=evidence, terminal_event=terminal_event)

        return commit

    fail_no_effect = dispatch.fail_no_effect

    def capture_no_effect(claim, *, evidence, terminal_event):
        no_effect_evidence.append(evidence)
        return fail_no_effect(claim, evidence=evidence, terminal_event=terminal_event)

    no_effect_evidence = evidence
    monkeypatch.setattr(dispatch, "fail_no_effect", terminal(capture_no_effect))
    monkeypatch.setattr(dispatch, "mark_uncertain", terminal(dispatch.mark_uncertain))
    guarded = FencedEffectToolGateway(
        gateway,
        dispatch=dispatch,
        artifacts=SQLiteArtifactPayloadStore(tmp_path / "lifecycle.db"),
        execution_session_id=session_id,
        root_session_id=session_id,
        fence=_fence(),
        claim_ttl=timedelta(seconds=30),
        authority_scope="workspace-write",
        next_event=lambda kind, actor, payload: SessionEvent.create(
            session_id=session_id,
            sequence=len(accepted),
            event_type=kind,
            actor=actor,
            payload=payload,
        ),
        accept_event=accepted.append,
        ownership_check=require_owned,
        execution_started=started,
    )
    finished = []

    def finish(call, result):
        finished.append((call, result))
        raise RuntimeError("terminal observer unavailable")

    guarded.execution_finished_listener = finish
    call = _call("command.run")
    error_type, message = {
        "lease_loss": (LeaseLostError, "callback lost lease"),
        "callback_error": (RuntimeError, "start observer failed"),
        "provider_error": (TimeoutError, "provider outcome unknown"),
        "provider_cancel": (CancelledError, "provider cancelled"),
    }[failure]

    with pytest.raises(error_type, match=message) as raised:
        guarded.execute(call)

    dispatched = failure in {"provider_error", "provider_cancel"}
    assert gateway.calls == int(dispatched)
    assert dispatch.uncertain == int(dispatched and not terminal_rejected)
    assert dispatch.failed_no_effect == int(not dispatched and not terminal_rejected)
    assert dispatch.last_claim is not None
    assert finished == [(call, None)]
    assert "terminal observer unavailable" in " ".join(raised.value.__notes__)
    assert terminal_attempts == [
        "provider_call_raised" if dispatched else "provider_call_not_dispatched"
    ]
    if terminal_rejected:
        expected_note = (
            "terminal commit cancelled"
            if terminal_rejected == "cancelled"
            else "terminal fence rejected"
        )
        assert expected_note in " ".join(raised.value.__notes__)
        assert len(accepted) == 1  # no unowned terminal Event was accepted
    else:
        assert accepted[-1].event_type is EventType.TOOL_EXECUTION_FAILED
        metadata = accepted[-1].payload["metadata"]
        assert metadata["effect_status"] == ("uncertain" if dispatched else "failed_no_effect")
        if not dispatched:
            assert metadata["execution_state"] == "not_executed"
            assert evidence[0].reason_code == "provider_call_not_dispatched"


@pytest.mark.parametrize("name", ["files.read", "events.get_event"])
@pytest.mark.parametrize("owned", [False, True])
def test_read_only_paths_keep_ownership_check_without_effect_observers(tmp_path, name, owned):
    from tests.agent_tools.test_effect_guard import _HostReadGateway

    gateway = _HostReadGateway()
    dispatch = _Dispatch()
    session_id = new_session_id()

    def require_owned():
        if not owned:
            raise LeaseLostError("read lease lost")

    def unexpected(*_args):
        pytest.fail("read-only execution must not enter Effect lifecycle")

    guarded = FencedEffectToolGateway(
        gateway,
        dispatch=dispatch,
        artifacts=SQLiteArtifactPayloadStore(tmp_path / "read.db"),
        execution_session_id=session_id,
        root_session_id=session_id,
        fence=_fence(),
        claim_ttl=timedelta(seconds=30),
        authority_scope="workspace-write",
        next_event=unexpected,
        accept_event=unexpected,
        ownership_check=require_owned,
        execution_started=unexpected,
    )
    guarded.execution_finished_listener = unexpected
    if owned:
        assert guarded.execute(_call(name)).output == "ok"
    else:
        with pytest.raises(LeaseLostError, match="read lease lost"):
            guarded.execute(_call(name))
    assert gateway.calls == int(owned)
    assert dispatch.last_claim is None


@pytest.mark.parametrize(
    "fault", ["none", "observer_error", "lookup_cancel", "commit_cancel", "observer_cancel"]
)
def test_unreadable_old_payload_settles_its_authoritative_intent(tmp_path, monkeypatch, fault):
    from agent_core.domain.effect_dispatch import EffectScheduleRequest
    from agent_tools.effect_guard_support import effect_identity

    gateway, dispatch = _Gateway(), _Dispatch()
    session_id = new_session_id()
    original, caller = _call("command.run"), _call("files.write")
    intent = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.TOOL_EXECUTION_STARTED,
        actor=EventActor.HARNESS,
        payload={
            "tool_name": original.name,
            "tool_call_id": str(original.tool_call_id),
            "attempt_number": 3,
        },
    )
    identity = effect_identity(original, "workspace-write")
    dispatch.schedule(
        EffectScheduleRequest(
            root_session_id=session_id,
            identity=identity,
            request_hash=identity.canonical_effect_hash,
            payload_artifact_ref=f"artifact://{new_session_id()}",
            started_event=intent,
        ),
        fence=_fence(),
    )

    def read_intent(_claimed):
        if fault == "lookup_cancel":
            raise CancelledError("intent lookup cancelled")
        return intent

    monkeypatch.setattr(dispatch, "read_intent_event", read_intent, raising=False)
    if fault == "commit_cancel":

        def cancelled_commit(*_args, **_kwargs):
            raise CancelledError("payload settlement cancelled")

        monkeypatch.setattr(dispatch, "fail_no_effect", cancelled_commit)
    accepted, finished = [intent], []
    guarded = FencedEffectToolGateway(
        gateway,
        dispatch=dispatch,
        artifacts=SQLiteArtifactPayloadStore(tmp_path / "admission.db"),
        execution_session_id=session_id,
        root_session_id=session_id,
        fence=_fence(),
        claim_ttl=timedelta(seconds=30),
        authority_scope="workspace-write",
        next_event=lambda kind, actor, payload: SessionEvent.create(
            session_id=session_id,
            sequence=len(accepted),
            event_type=kind,
            actor=actor,
            payload=payload,
        ),
        accept_event=accepted.append,
        ownership_check=lambda: None,
    )
    primary = TimeoutError("payload unavailable")

    def read(_ref):
        raise primary

    def finish(call, result):
        finished.append((call, result))
        if fault == "observer_cancel":
            raise CancelledError("observer cancelled")
        if fault == "observer_error":
            raise RuntimeError("observer unavailable")

    monkeypatch.setattr(guarded, "_read_tool_call", read)
    guarded.execution_finished_listener = finish
    with pytest.raises(TimeoutError) as raised:
        guarded.execute(caller)
    assert raised.value is primary
    assert gateway.calls == dispatch.uncertain == 0
    settled = fault not in {"lookup_cancel", "commit_cancel"}
    assert dispatch.failed_no_effect == int(settled)
    if fault == "lookup_cancel":
        assert finished == []  # Missing authoritative identity cannot be fabricated.
        assert "intent lookup cancelled" in " ".join(primary.__notes__)
        return
    if not settled:
        assert len(finished) == 1
        assert finished[0][0].tool_call_id == original.tool_call_id
        assert finished[0][1] is None
        assert "payload settlement cancelled" in " ".join(primary.__notes__)
        return
    assert accepted[-1].event_type is EventType.TOOL_EXECUTION_FAILED
    assert accepted[-1].payload["tool_call_id"] == str(original.tool_call_id)
    assert accepted[-1].payload["tool_name"] == original.name
    assert accepted[-1].payload["attempt_number"] == 3
    assert accepted[-1].payload["metadata"]["execution_state"] == "not_executed"
    assert len(finished) == 1 and finished[0][1] is None
    identity_only = finished[0][0]
    assert identity_only.tool_call_id == original.tool_call_id
    assert identity_only.name == original.name and identity_only.arguments == {}
    assert identity_only.created_at == intent.created_at
    if fault == "observer_error":
        assert "observer unavailable" in " ".join(primary.__notes__)
    if fault == "observer_cancel":
        assert "observer cancelled" in " ".join(primary.__notes__)


@pytest.mark.parametrize(
    "fault", ["missing", "event", "session", "type", "name", "attempt", "call_id", "settlement"]
)
def test_payload_admission_recovery_fails_closed_without_replacing_primary(fault):
    from contextlib import nullcontext
    from unittest.mock import Mock

    from agent_core.domain.effect_dispatch import EffectScheduleRequest
    from agent_tools.effect_guard_support import effect_identity
    from agent_tools.effect_payload_admission import settle_unreadable_payload

    session_id, dispatch = new_session_id(), _Dispatch()
    call = _call("command.run")
    intent = SessionEvent.create(
        session_id=session_id,
        sequence=0,
        event_type=EventType.TOOL_EXECUTION_STARTED,
        actor=EventActor.HARNESS,
        payload={
            "tool_name": call.name,
            "tool_call_id": str(call.tool_call_id),
            "attempt_number": 1,
        },
    )
    identity = effect_identity(call, "write")
    dispatch.schedule(
        EffectScheduleRequest(
            root_session_id=session_id,
            identity=identity,
            request_hash=identity.canonical_effect_hash,
            payload_artifact_ref=f"artifact://{new_session_id()}",
            started_event=intent,
        ),
        fence=_fence(),
    )
    claim = dispatch.claim_next(session_id, fence=_fence(), claim_ttl=timedelta(seconds=30))
    changed = {
        "event": {"event_id": new_session_id()},
        "session": {"session_id": new_session_id()},
        "type": {"event_type": EventType.SESSION_COMPLETED},
        "name": {"payload": {**intent.payload, "tool_name": "files.write"}},
        "attempt": {"payload": {**intent.payload, "attempt_number": True}},
        "call_id": {"payload": {**intent.payload, "tool_call_id": "invalid"}},
    }
    dispatch.read_intent_event = Mock(return_value=intent.model_copy(update=changed.get(fault, {})))
    if fault == "missing":
        dispatch.read_intent_event.side_effect = RuntimeError("intent unavailable")
    if fault == "settlement":
        dispatch.fail_no_effect = Mock(side_effect=RuntimeError("fenced commit unavailable"))
    accepted = Mock()
    primary = TimeoutError("original payload read failed")
    recovered = settle_unreadable_payload(
        claim,
        primary,
        dispatch=dispatch,
        ownership_check=lambda: None,
        mutation_guard=nullcontext,
        next_event=lambda kind, actor, payload: SessionEvent.create(
            session_id=session_id,
            sequence=1,
            event_type=kind,
            actor=actor,
            payload=payload,
        ),
        accept_event=accepted,
    )
    assert str(primary) == "original payload read failed"
    assert "settlement failed" in " ".join(primary.__notes__)
    accepted.assert_not_called()
    assert (recovered is not None) == (fault == "settlement")
