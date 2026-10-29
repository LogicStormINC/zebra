"""Complete standard responses are input, never independent execution authority."""

import pytest
from ag_ui.core import RunAgentInput


def value(resume):
    return RunAgentInput.model_validate(
        {
            "threadId": "task",
            "runId": "agui:" + "a" * 64,
            "state": {},
            "messages": [],
            "tools": [],
            "context": [],
            "forwardedProps": {},
            "resume": resume,
        }
    )


@pytest.mark.parametrize(
    "entries",
    [
        [],
        [{"interruptId": "approval:old", "status": "resolved", "payload": {}}],
        [{"interruptId": "approval:one", "status": "resolved"}] * 2,
        [
            {"interruptId": "approval:one", "status": "resolved"},
            {"interruptId": "approval:other", "status": "resolved"},
        ],
        [{"interruptId": "approval:one", "status": "resolved", "extraAuthority": True}],
    ],
)
def test_entire_response_set_is_validated_before_native_dispatch(entries):
    from zebra_agent_api.ag_ui_native_interaction import validate_response_set

    with pytest.raises(ValueError):
        validate_response_set(value(entries), "agui:" + "a" * 64, ["approval:one"])


def test_response_set_accepts_exact_coverage_and_rejects_old_run_or_non_json():
    from zebra_agent_api.ag_ui_native_interaction import validate_response_set

    response = value([{"interruptId": "approval:one", "status": "resolved", "payload": {}}])
    assert len(validate_response_set(response, response.run_id, ["approval:one"])) == 1
    with pytest.raises(ValueError):
        validate_response_set(response, "agui:" + "b" * 64, ["approval:one"])
    response.resume[0].payload = {"value": float("nan")}
    with pytest.raises(ValueError):
        validate_response_set(response, response.run_id, ["approval:one"])


@pytest.mark.parametrize(
    "result",
    [
        {},
        {"view": {"ids": ["1"], "label": "opened"}},
        {"view": {"ids": [True], "label": "opened"}},
        {"view": {"ids": [-1], "label": "opened"}},
        {"view": {"ids": [1, 2, 3], "label": "opened"}},
        {"view": {"ids": [1], "label": "other"}},
        {"view": {"ids": [1], "label": "opened", "extra": True}},
    ],
)
def test_native_succeeded_result_uses_the_published_restricted_schema(result):
    from agent_control_plane.client_effects import validate_client_effect_result

    receipt, contract = result_contract(result)
    with pytest.raises(ValueError):
        validate_client_effect_result(receipt, contract)


def result_contract(result, status="succeeded"):
    from datetime import UTC, datetime
    from uuid import uuid4

    from agent_core.domain.client_capabilities import ClientActionContract
    from agent_core.domain.client_effects import ClientEffectReceipt

    contract = ClientActionContract(
        name="app.ui.open",
        risk="presentation",
        result_schema={
            "type": "object",
            "properties": {
                "view": {
                    "type": "object",
                    "properties": {
                        "ids": {
                            "type": "array",
                            "items": {"type": "integer", "minimum": 0},
                            "minItems": 1,
                            "maxItems": 2,
                        },
                        "label": {"type": "string", "enum": ["opened"]},
                    },
                    "required": ["ids", "label"],
                    "additionalProperties": False,
                }
            },
            "required": ["view"],
            "additionalProperties": False,
        },
    )
    return ClientEffectReceipt(
        receipt_id=uuid4(),
        effect_id=uuid4(),
        idempotency_key="native-result",
        request_digest="a" * 64,
        status=status,
        result=result,
        received_at=datetime.now(UTC),
    ), contract


def test_valid_native_result_and_failure_shapes_preserve_their_contracts():
    from agent_control_plane.client_effects import validate_client_effect_result

    receipt, contract = result_contract({"view": {"ids": [0, 2], "label": "opened"}})
    validate_client_effect_result(receipt, contract)
    for status in ("failed", "declined", "unavailable", "stale_ui_state"):
        failure, _ = result_contract({"error": "application unavailable"}, status)
        validate_client_effect_result(failure, contract)
    with pytest.raises(ValueError):
        validate_client_effect_result(receipt, contract.model_copy(update={"max_result_bytes": 4}))
