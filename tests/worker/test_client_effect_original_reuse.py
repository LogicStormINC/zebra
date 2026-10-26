"""Original receipt observation is historical evidence, never new UI execution authority."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agent_core.domain.client_effects import ClientEffectReceipt, ClientEffectStatus
from agent_core.domain.identifiers import new_client_run_binding_id, new_session_id
from agent_core.domain.tools import ToolCallStatus
from agent_tools.effect_guard_support import reuse_result
from zebra_agent_worker.client_tool_gateway import ClientToolGateway

from tests.worker.test_client_tool_gateway import _call, _gateway


def sample():
    first, recorder = _gateway()
    original_call = _call()
    original = first.execute(original_call)
    request = recorder.scheduled[0]
    receipt = ClientEffectReceipt(
        receipt_id=uuid4(),
        effect_id=request.effect_id,
        idempotency_key=request.idempotency_key,
        request_digest=request.request_digest,
        status=ClientEffectStatus.SUCCEEDED,
        result={"opened": True},
        received_at=datetime.now(UTC),
    )

    class Originals:
        effect = request
        result = receipt
        reads = 0

        def schedule(self, *args, **kwargs):
            pytest.fail("original reconciliation attempted another dispatch")

        def get_effect(self, effect_id):
            assert effect_id == request.effect_id
            self.reads += 1
            return self.effect

        def read_receipt(self, effect_id):
            assert effect_id == request.effect_id
            self.reads += 1
            return self.result

    store = Originals()
    current = replace(
        first.context,
        session_id=new_session_id(),
        binding=first.context.binding.model_copy(
            update={"run_id": "run-2", "binding_id": new_client_run_binding_id()}
        ),
        ui_revision=8,
    )
    gateway = ClientToolGateway(context=current, dispatch=store, receipts=store)
    return gateway, store, original, request, receipt, first.context, original_call


@pytest.mark.parametrize(
    "status",
    [
        ClientEffectStatus.SUCCEEDED,
        ClientEffectStatus.FAILED,
        ClientEffectStatus.DECLINED,
        ClientEffectStatus.UNAVAILABLE,
        ClientEffectStatus.STALE_UI_STATE,
    ],
)
def test_terminal_original_receipt_is_not_a_new_ui_effect(status):
    gateway, store, original, request, receipt, _, _ = sample()
    store.result = receipt.model_copy(update={"status": status})
    call = _call()
    result = reuse_result(gateway, call, original)
    assert result.tool_call_id == call.tool_call_id
    assert result.metadata["historical_client_effect"] is True
    assert result.metadata["current_ui_performed"] is False
    assert result.metadata["original_client_effect_run_id"] == request.run_id
    assert result.status is (
        ToolCallStatus.EXECUTED if status is ClientEffectStatus.SUCCEEDED else ToolCallStatus.FAILED
    )
    assert not result.metadata.get("client_effect_deferred")
    assert store.reads == 2 and original.metadata["client_effect_deferred"] is True


@pytest.mark.parametrize(
    "fault",
    [
        "no-effect",
        "no-receipt",
        "digest",
        "receipt-effect",
        "other-task",
        "different-args",
        "different-contract",
        "pending",
        "malformed-id",
        "read-outage",
        "receipt-unknown",
    ],
)
def test_unknown_and_mismatched_original_never_schedule_or_wait_on_prior_run(fault):
    gateway, store, original, _, receipt, _, _ = sample()
    if fault == "no-effect":
        store.effect = None
    if fault == "no-receipt":
        store.result = None
    if fault == "digest":
        store.result = receipt.model_copy(update={"request_digest": "e" * 64})
    if fault == "receipt-effect":
        store.result = receipt.model_copy(update={"effect_id": uuid4()})
    if fault == "other-task":
        store.effect = store.effect.model_copy(update={"task_id": uuid4()})
    if fault == "different-args":
        store.effect = store.effect.model_copy(update={"arguments": {"itemId": "other"}})
    if fault == "different-contract":
        store.effect = store.effect.model_copy(update={"action_contract_digest": "e" * 64})
    if fault == "pending":
        store.result = None
    if fault == "malformed-id":
        original = original.model_copy(
            update={"metadata": {**original.metadata, "client_effect_id": "bad"}}
        )
    if fault == "read-outage":
        store.read_receipt = lambda _: (_ for _ in ()).throw(RuntimeError("unavailable"))
    if fault == "receipt-unknown":
        store.result = receipt.model_copy(update={"status": ClientEffectStatus.UNCERTAIN})
    result = reuse_result(gateway, _call(), original)
    assert result.status is ToolCallStatus.FAILED
    assert result.metadata["execution_state"] == "unknown"
    assert not result.metadata.get("client_effect_deferred")
    assert "historical_client_effect" not in result.metadata


def test_exact_original_pending_recovery_can_still_wait_on_its_own_run():
    _, store, original, _, _, first_context, call = sample()
    store.result = None
    gateway = ClientToolGateway(context=first_context, dispatch=store, receipts=store)
    assert reuse_result(gateway, call, original) is original


def test_owner_loss_after_receipt_read_is_not_masked():
    gateway, store, original, *_ = sample()

    def lost():
        assert store.reads == 2
        raise RuntimeError("lease lost")

    with pytest.raises(RuntimeError, match="lease lost"):
        reuse_result(gateway, _call(), original, lost)
