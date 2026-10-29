"""Optional native preparation preserves old receipt-port calls by default."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agent_control_plane.client_effects import ClientEffectReceiptService
from agent_core.domain.client_effects import ClientEffectReceipt


def test_optional_preparation_reaches_same_receipt_once_and_legacy_call_shape_is_kept():
    from agent_core.domain.client_preparation import ClientPreparationContext

    receipt = ClientEffectReceipt(
        receipt_id=uuid4(),
        effect_id=uuid4(),
        idempotency_key="original-receipt",
        request_digest="a" * 64,
        status="succeeded",
        received_at=datetime.now(UTC),
    )
    received = []

    class Port:
        def accept_receipt(self, value, **kwargs):
            received.append((value, kwargs))
            return "accepted"

    service = ClientEffectReceiptService(Port())
    session = uuid4()
    args = {"request_fence_hash": "b" * 64, "session_id": session, "controller": True}
    assert service.submit(receipt, **args) == "accepted"
    assert "preparation" not in received[0][1]
    context = ClientPreparationContext(
        operation_id=uuid4(),
        client_session_id=uuid4(),
        task_id=uuid4(),
        run_id="native",
        projection_version="test:r2",
        request_hash="c" * 64,
        input={"messages": []},
        previous_run_id="agui:" + "d" * 64,
    )
    assert service.submit(receipt, **args, preparation=context) == "accepted"
    assert received[1][1]["preparation"] == context
    with pytest.raises(ValueError):
        ClientPreparationContext.model_validate(
            {**context.model_dump(), "input": {"bad": float("nan")}}
        )
