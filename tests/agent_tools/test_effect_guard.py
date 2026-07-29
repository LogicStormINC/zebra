from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_core.domain.effect_dispatch import (
    EffectClaim,
    EffectDispatch,
    EffectDispatchStatus,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_session_id, new_tool_call_id
from agent_core.domain.leases import LeaseFence, LeaseLostError
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_storage import SQLiteArtifactPayloadStore, SQLiteEffectLedger
from agent_tools import EffectGuardedToolGateway, FencedEffectToolGateway


class _Gateway:
    model_tools = ()
    effective_mcp_tools = ()
    effective_skill_components = ()
    parallel_safe_tools = frozenset()
    parallel_batch_limits = {}

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.calls += 1
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output="ok",
        )

    def resolve_model_tool_calls(self, tool_calls: tuple[ToolCall, ...]):
        return tool_calls

    def close(self) -> None:
        pass


class _Dispatch:
    def __init__(self) -> None:
        self.pending: EffectDispatch | None = None
        self.reconcilable: tuple[EffectClaim, ...] = ()
        self.reconciled = 0
        self.uncertain = 0
        self.last_claim: EffectClaim | None = None

    def schedule(self, request, *, fence):
        del fence
        if self.pending is not None:
            return self.pending
        self.pending = EffectDispatch(
            dispatch_id=uuid4(),
            execution_session_id=request.execution_session_id,
            root_session_id=request.root_session_id,
            identity=request.identity,
            attempt=1,
            request_hash=request.request_hash,
            payload_artifact_ref=request.payload_artifact_ref,
            status=EffectDispatchStatus.PENDING,
            intent_event_id=request.started_event.event_id,
            created_at=request.started_event.created_at,
            updated_at=request.started_event.created_at,
        )
        return self.pending

    def claim_next(self, execution_session_id, *, fence, claim_ttl):
        del execution_session_id, claim_ttl
        assert self.pending is not None
        claimed = self.pending.model_copy(
            update={
                "status": EffectDispatchStatus.CLAIMED,
                "updated_at": self.pending.updated_at + timedelta(microseconds=1),
            }
        )
        self.pending = None
        self.last_claim = EffectClaim(
            dispatch=claimed,
            claim_fence=fence,
            claim_expires_at=claimed.updated_at + timedelta(seconds=30),
        )
        return self.last_claim

    def complete(self, claim, *, result, terminal_event):
        del claim, result
        return terminal_event

    def mark_uncertain(self, claim, *, evidence, terminal_event):
        del claim, evidence
        self.uncertain += 1
        return terminal_event

    def list_reconcilable(self, execution_session_id, *, current_fence, limit=100):
        del execution_session_id, current_fence
        return self.reconcilable[:limit]

    def reconcile_expired(self, dispatch_id, *, old_claim, current_fence, evidence):
        del dispatch_id, current_fence, evidence
        self.reconciled += 1
        return old_claim.dispatch.model_copy(
            update={"status": EffectDispatchStatus.UNCERTAIN}
        )


def _call(name: str) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments={"command": "deploy"},
        created_at=datetime.now(UTC),
    )


def test_effectful_duplicate_reuses_result_but_read_only_calls_execute(tmp_path) -> None:
    gateway = _Gateway()
    guarded = EffectGuardedToolGateway(
        gateway,
        ledger=SQLiteEffectLedger(tmp_path / "ledger.db"),
        root_session_id=new_session_id(),
        authority_scope="workspace-write",
    )

    first = guarded.execute(_call("command.run"))
    replay = guarded.execute(_call("command.run"))
    guarded.execute(_call("files.read"))
    guarded.execute(_call("files.read"))

    assert replay.output == first.output
    assert gateway.calls == 3


def test_fenced_effect_persists_intent_and_terminal_around_provider(tmp_path) -> None:
    gateway = _Gateway()
    dispatch = _Dispatch()
    session_id = new_session_id()
    accepted: list[SessionEvent] = []
    next_sequence = 0

    def next_event(
        event_type: EventType,
        actor: EventActor,
        payload: dict[str, object],
    ) -> SessionEvent:
        nonlocal next_sequence
        event = SessionEvent.create(
            session_id=session_id,
            sequence=next_sequence,
            event_type=event_type,
            actor=actor,
            payload={"attempt_number": 1, **payload},
        )
        next_sequence += 1
        return event

    guarded = FencedEffectToolGateway(
        gateway,
        dispatch=dispatch,
        artifacts=SQLiteArtifactPayloadStore(tmp_path / "effects.db"),
        execution_session_id=session_id,
        root_session_id=session_id,
        fence=_fence(),
        claim_ttl=timedelta(seconds=30),
        authority_scope="workspace-write",
        next_event=next_event,
        accept_event=accepted.append,
        ownership_check=lambda: None,
    )

    result = guarded.execute(_call("command.run"))

    assert result.output == "ok"
    assert gateway.calls == 1
    assert [event.event_type for event in accepted] == [
        EventType.TOOL_EXECUTION_STARTED,
        EventType.TOOL_EXECUTION_COMPLETED,
    ]


def test_fenced_effect_failed_result_becomes_uncertain(tmp_path) -> None:
    class FailedGateway(_Gateway):
        def execute(self, tool_call: ToolCall) -> ToolResult:
            self.calls += 1
            return ToolResult(
                tool_call_id=tool_call.tool_call_id,
                status=ToolCallStatus.FAILED,
                output="provider response ambiguous",
                metadata={"provider_operation_id": "operation-1"},
            )

    dispatch = _Dispatch()
    session_id = new_session_id()
    sequence = 0

    def next_event(event_type, actor, payload):
        nonlocal sequence
        event = SessionEvent.create(
            session_id=session_id,
            sequence=sequence,
            event_type=event_type,
            actor=actor,
            payload={"attempt_number": 1, **payload},
        )
        sequence += 1
        return event

    guarded = FencedEffectToolGateway(
        FailedGateway(),
        dispatch=dispatch,
        artifacts=SQLiteArtifactPayloadStore(tmp_path / "effects.db"),
        execution_session_id=session_id,
        root_session_id=session_id,
        fence=_fence(),
        claim_ttl=timedelta(seconds=30),
        authority_scope="workspace-write",
        next_event=next_event,
        accept_event=lambda event: event,
        ownership_check=lambda: None,
    )

    result = guarded.execute(_call("command.run"))

    assert result.status is ToolCallStatus.FAILED
    assert dispatch.uncertain == 1


def test_provider_success_commit_crash_recovers_as_uncertain_without_replay(tmp_path) -> None:
    class CommitCrashDispatch(_Dispatch):
        def complete(self, claim, *, result, terminal_event):
            del claim, result, terminal_event
            raise RuntimeError("terminal commit unavailable")

    gateway = _Gateway()
    dispatch = CommitCrashDispatch()
    session_id = new_session_id()
    sequence = 0

    def next_event(event_type, actor, payload):
        nonlocal sequence
        event = SessionEvent.create(
            session_id=session_id,
            sequence=sequence,
            event_type=event_type,
            actor=actor,
            payload=payload,
        )
        sequence += 1
        return event

    guarded = FencedEffectToolGateway(
        gateway,
        dispatch=dispatch,
        artifacts=SQLiteArtifactPayloadStore(tmp_path / "effects.db"),
        execution_session_id=session_id,
        root_session_id=session_id,
        fence=_fence(),
        claim_ttl=timedelta(seconds=30),
        authority_scope="workspace-write",
        next_event=next_event,
        accept_event=lambda event: event,
        ownership_check=lambda: None,
    )

    with pytest.raises(RuntimeError, match="terminal commit unavailable"):
        guarded.execute(_call("command.run"))

    assert dispatch.last_claim is not None
    dispatch.reconcilable = (dispatch.last_claim,)
    guarded.reconcile_expired()
    assert gateway.calls == 1
    assert dispatch.reconciled == 1


def test_terminal_response_loss_replays_durable_result_without_provider_call(tmp_path) -> None:
    class DurableTerminalDispatch(_Dispatch):
        def __init__(self) -> None:
            super().__init__()
            self.terminal: EffectDispatch | None = None

        def schedule(self, request, *, fence):
            if self.terminal is not None:
                return self.terminal
            return super().schedule(request, fence=fence)

        def complete(self, claim, *, result, terminal_event):
            self.terminal = claim.dispatch.model_copy(
                update={
                    "status": EffectDispatchStatus.SUCCEEDED,
                    "result": result,
                    "terminal_event_id": terminal_event.event_id,
                    "updated_at": terminal_event.created_at,
                }
            )
            return terminal_event

    gateway = _Gateway()
    dispatch = DurableTerminalDispatch()
    session_id = new_session_id()
    sequence = 0
    lose_response = True

    def next_event(event_type, actor, payload):
        nonlocal sequence
        event = SessionEvent.create(
            session_id=session_id,
            sequence=sequence,
            event_type=event_type,
            actor=actor,
            payload=payload,
        )
        sequence += 1
        return event

    def accept_event(event: SessionEvent) -> None:
        nonlocal lose_response
        if event.event_type is EventType.TOOL_EXECUTION_COMPLETED and lose_response:
            lose_response = False
            raise RuntimeError("response lost after commit")

    guarded = FencedEffectToolGateway(
        gateway,
        dispatch=dispatch,
        artifacts=SQLiteArtifactPayloadStore(tmp_path / "effects.db"),
        execution_session_id=session_id,
        root_session_id=session_id,
        fence=_fence(),
        claim_ttl=timedelta(seconds=30),
        authority_scope="workspace-write",
        next_event=next_event,
        accept_event=accept_event,
        ownership_check=lambda: None,
    )

    with pytest.raises(RuntimeError, match="response lost after commit"):
        guarded.execute(_call("command.run"))
    replay = guarded.execute(_call("command.run"))

    assert replay.output == "ok"
    assert gateway.calls == 1


def test_lease_loss_after_schedule_stops_provider_call(tmp_path) -> None:
    gateway = _Gateway()
    dispatch = _Dispatch()
    session_id = new_session_id()
    checks = 0
    accepted: list[SessionEvent] = []

    def require_owned() -> None:
        nonlocal checks
        checks += 1
        if checks > 1:
            raise LeaseLostError("stale fence")

    guarded = FencedEffectToolGateway(
        gateway,
        dispatch=dispatch,
        artifacts=SQLiteArtifactPayloadStore(tmp_path / "effects.db"),
        execution_session_id=session_id,
        root_session_id=session_id,
        fence=_fence(),
        claim_ttl=timedelta(seconds=30),
        authority_scope="workspace-write",
        next_event=lambda event_type, actor, payload: SessionEvent.create(
            session_id=session_id,
            sequence=len(accepted),
            event_type=event_type,
            actor=actor,
            payload=payload,
        ),
        accept_event=accepted.append,
        ownership_check=require_owned,
    )

    with pytest.raises(LeaseLostError, match="stale fence"):
        guarded.execute(_call("command.run"))

    assert gateway.calls == 0
    assert dispatch.pending is not None


def _fence() -> LeaseFence:
    return LeaseFence(
        control_plane_epoch=uuid4(),
        fencing_token=1,
        owner_instance_id="worker-a",
    )
