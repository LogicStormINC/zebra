from datetime import UTC, datetime, timedelta
from uuid import uuid4

from agent_core.domain.effect_dispatch import EffectClaim, EffectDispatch, EffectDispatchStatus
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.host_effect_receipts import HostEffectReceipt, HostEffectStatus
from agent_core.domain.identifiers import new_session_id, new_tool_call_id
from agent_core.domain.leases import LeaseFence
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_storage import SQLiteArtifactPayloadStore
from agent_tools import FencedEffectToolGateway


class _Dispatch:
    def __init__(self) -> None:
        self.pending: EffectDispatch | None = None
        self.uncertain: EffectDispatch | None = None
        self.resolved = 0

    def schedule(self, request, *, fence):
        del fence
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
        claimed = self.pending.model_copy(update={"status": EffectDispatchStatus.CLAIMED})
        self.pending = None
        return EffectClaim(
            dispatch=claimed,
            claim_fence=fence,
            claim_expires_at=claimed.updated_at + timedelta(seconds=30),
        )

    def mark_uncertain(self, claim, *, evidence, terminal_event):
        self.uncertain = claim.dispatch.model_copy(
            update={"status": EffectDispatchStatus.UNCERTAIN, "evidence": evidence}
        )
        return terminal_event

    def list_uncertain(self, execution_session_id, *, current_fence, limit=100):
        del execution_session_id, current_fence, limit
        return () if self.uncertain is None else (self.uncertain,)

    def resolve_uncertain(
        self, dispatch_id, *, current_fence, evidence, outcome, terminal_event, result=None
    ):
        del dispatch_id, current_fence, evidence, outcome, result
        self.resolved += 1
        self.uncertain = None
        return terminal_event


class _Gateway:
    model_tools = ()
    effective_mcp_tools = ()
    effective_skill_components = ()
    parallel_safe_tools = frozenset()
    parallel_batch_limits = {}

    def __init__(self, uncertain: HostEffectReceipt) -> None:
        self.uncertain = uncertain
        self.calls = 0

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.calls += 1
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.FAILED,
            metadata={
                "transport_outcome": "timed_out",
                "business_outcome": "unknown",
                "provider_operation_id": self.uncertain.provider_operation_id,
                "host_effect_receipt": self.uncertain.model_dump(mode="json"),
            },
        )

    def reconcile_effect_receipt(self, receipt: HostEffectReceipt) -> HostEffectReceipt:
        assert receipt == self.uncertain
        return receipt.model_copy(
            update={
                "effect_status": HostEffectStatus.SUCCEEDED,
                "business_revision": "revision-9",
            }
        )

    def resolve_model_tool_calls(self, calls):
        return calls

    def close(self) -> None:
        pass


def test_durable_host_receipt_reconciles_without_replaying_write(tmp_path) -> None:
    operation_id = "host:operation-1"
    uncertain = HostEffectReceipt(
        provider_operation_id=operation_id,
        effect_status=HostEffectStatus.UNCERTAIN,
        received_at=datetime.now(UTC),
    )
    gateway = _Gateway(uncertain)
    dispatch = _Dispatch()
    session_id = new_session_id()
    sequence = 0
    accepted: list[SessionEvent] = []

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
        artifacts=SQLiteArtifactPayloadStore(tmp_path / "reconcile.db"),
        execution_session_id=session_id,
        root_session_id=session_id,
        fence=LeaseFence(
            control_plane_epoch=uuid4(), fencing_token=1, owner_instance_id="worker-a"
        ),
        claim_ttl=timedelta(seconds=30),
        authority_scope="workspace-write",
        next_event=next_event,
        accept_event=accepted.append,
        ownership_check=lambda: None,
    )
    call = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="command.run",
        arguments={"command": "deploy"},
        created_at=datetime.now(UTC),
    )

    guarded.execute(call)
    assert guarded.reconcile_uncertain() == 1

    assert gateway.calls == 1
    assert dispatch.resolved == 1
    assert [event.event_type for event in accepted] == [
        EventType.TOOL_EXECUTION_STARTED,
        EventType.TOOL_EXECUTION_FAILED,
        EventType.TOOL_EXECUTION_COMPLETED,
    ]
