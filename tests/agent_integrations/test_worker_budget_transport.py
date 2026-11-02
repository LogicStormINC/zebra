"""Exact transport proof and strict raw usage regressions (no external model)."""

from hashlib import sha256

import pytest
from agent_core.ports.worker_budget import (
    ModelBudgetReservation,
    ModelRequestBudget,
    WorkerBudgetError,
    trusted_usage,
)
from agent_integrations.worker_budget import inspect_request


def test_inspection_cannot_substitute_bytes():
    body = {"max_tokens": 5, "messages": []}

    class Gateway:
        _client = None

        def model_request_budget(self, exact):
            other = b"{}"
            return ModelRequestBudget(other, sha256(other).hexdigest(), 1, 5, "test-counter/1")

    with pytest.raises(WorkerBudgetError):
        inspect_request(Gateway(), body)


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        {"prompt_tokens": True, "completion_tokens": 1, "total_tokens": 2},
        {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 3},
        {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
    ],
)
def test_usage_is_not_coerced_or_guessed(usage):
    with pytest.raises(WorkerBudgetError):
        trusted_usage(usage, ModelBudgetReservation("id", "a" * 64, 2, 2))


class _Gate:
    def __init__(self):
        self.reserved = []
        self.settled = []

    def before_model(self, request):
        result = ModelBudgetReservation(
            str(len(self.reserved)),
            request.request_digest,
            request.input_upper_bound,
            request.output_cap,
        )
        self.reserved.append((request, result))
        return result

    def check(self):
        return 10

    def after_model(self, reservation, payload):
        trusted_usage(payload.get("usage"), reservation)
        self.settled.append(payload)


def _gateway(handler):
    import httpx
    from agent_integrations.openai_compatible import OpenAICompatibleModelGateway

    gateway = OpenAICompatibleModelGateway(
        provider_name="fixture",
        base_url="https://fixture.invalid",
        api_key="fixture",
        model_name="fixture",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    gateway.worker_budget = _Gate()
    return gateway


def _proof(exact):
    import json

    return ModelRequestBudget(
        exact,
        sha256(exact).hexdigest(),
        10,
        json.loads(exact).get("max_tokens", 5),
        "fixture-finite-vocab/1",
    )


def test_missing_real_counter_refuses_before_any_wire():
    sent = []
    gateway = _gateway(lambda request: sent.append(request))
    with pytest.raises(WorkerBudgetError, match="counter"):
        gateway.complete([])
    assert not sent and not gateway.worker_budget.reserved


def test_normal_guarded_chat_commits_exact_bytes_before_wire():
    import httpx
    from agent_integrations.worker_budget import guarded_chat

    sent = []

    def handler(request):
        proof, _ = gateway.worker_budget.reserved[0]
        assert request.content == proof.exact_body
        sent.append(request)
        return httpx.Response(
            200,
            json={
                "id": "provider-1",
                "model": "fixture",
                "choices": [
                    {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            },
        )

    gateway = _gateway(handler)
    gateway.model_request_budget = _proof
    result = guarded_chat(
        gateway, {"max_tokens": 5}, tools=(), tool_names=(), resolved=None, metadata=None
    )
    assert result.assistant_message.content == "ok"
    assert len(sent) == len(gateway.worker_budget.settled) == 1


def test_wire_parse_failure_does_not_settle_or_retry():
    import httpx
    from agent_integrations.worker_budget import guarded_chat

    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(200, content=b"invalid-json")

    gateway = _gateway(handler)
    gateway.model_request_budget = _proof
    with pytest.raises(ValueError):
        guarded_chat(
            gateway, {"max_tokens": 5}, tools=(), tool_names=(), resolved=None, metadata=None
        )
    assert len(sent) == len(gateway.worker_budget.reserved) == 1
    assert not gateway.worker_budget.settled


def test_stream_interruption_keeps_full_unknown():
    import httpx
    from agent_integrations.worker_budget import guarded_chat

    content = (
        b'data: {"id":"p1","choices":[{"delta":{"content":"ok"},'
        b'"finish_reason":"stop"}],"usage":{"prompt_tokens":2,'
        b'"completion_tokens":1,"total_tokens":3}}\n\n'
    )
    gateway = _gateway(lambda request: httpx.Response(200, content=content))
    gateway.model_request_budget = _proof
    emitted = []
    with pytest.raises(WorkerBudgetError, match="interrupted"):
        guarded_chat(
            gateway,
            {"max_tokens": 5, "stream": True},
            tools=(),
            tool_names=(),
            resolved=None,
            metadata=None,
            sink=emitted.append,
        )
    assert emitted and not gateway.worker_budget.settled


def test_guarded_stream_with_usage_settles_after_true_terminal():
    import httpx
    from agent_integrations.worker_budget import guarded_chat

    content = (
        b'data: {"id":"p1","choices":[{"delta":{"content":"ok"},'
        b'"finish_reason":"stop"}],"usage":{"prompt_tokens":2,'
        b'"completion_tokens":1,"total_tokens":3}}\n\ndata: [DONE]\n\n'
    )
    gateway = _gateway(lambda request: httpx.Response(200, content=content))
    gateway.model_request_budget = _proof
    emitted = []
    result = guarded_chat(
        gateway,
        {"max_tokens": 5, "stream": True},
        tools=(),
        tool_names=(),
        resolved=None,
        metadata=None,
        sink=emitted.append,
    )
    assert result.assistant_message.content == "ok"
    assert len(emitted) == len(gateway.worker_budget.settled) == 1


def test_absolute_io_deadline_cancels_and_preserves_unknown():
    import asyncio

    from agent_integrations.worker_budget import guarded_chat

    async def slow(request):
        await asyncio.sleep(0.2)
        pytest.fail("I/O was not cancelled by the Task deadline")

    gateway = _gateway(slow)
    gateway.model_request_budget = _proof
    gateway.worker_budget.check = lambda: 0.01
    with pytest.raises(TimeoutError):
        guarded_chat(
            gateway, {"max_tokens": 5}, tools=(), tool_names=(), resolved=None, metadata=None
        )
    assert len(gateway.worker_budget.reserved) == 1 and not gateway.worker_budget.settled


def test_custom_sync_client_refused_before_reservation():
    import httpx
    from agent_integrations.worker_budget import guarded_chat

    gateway = _gateway(lambda _: pytest.fail("wire attempted"))
    gateway._client.close()
    gateway._client = httpx.Client()
    gateway.model_request_budget = _proof
    try:
        with pytest.raises(WorkerBudgetError, match="not cancellable"):
            guarded_chat(
                gateway, {"max_tokens": 5}, tools=(), tool_names=(), resolved=None, metadata=None
            )
        assert not gateway.worker_budget.reserved
    finally:
        gateway._client.close()


@pytest.mark.parametrize(
    "body",
    [
        {"max_tokens": 5, "messages": [{"content": [{"type": "image_url", "image_url": "x"}]}]},
        {"max_tokens": 5, "previous_response_id": "unknown-original"},
    ],
)
def test_unproven_images_and_continuation_never_send(body):
    gateway = _gateway(lambda _: pytest.fail("wire attempted"))
    gateway.model_request_budget = _proof
    with pytest.raises(WorkerBudgetError, match="image/continuation"):
        inspect_request(gateway, body)
    assert not gateway.worker_budget.reserved


def test_normal_generic_stream_requests_provider_usage_on_actual_wire():
    import json

    import httpx
    from agent_core.domain.modeling import ModelInvocationPolicy

    def reply(request):
        body = json.loads(request.content)
        assert body["stream_options"] == {"include_usage": True}
        return httpx.Response(
            200,
            content=(
                b'data: {"id":"s1","choices":[{"delta":{"content":"ok"},'
                b'"finish_reason":"stop"}],"usage":{"prompt_tokens":2,'
                b'"completion_tokens":1,"total_tokens":3}}\n\ndata: [DONE]\n\n'
            ),
        )

    gateway = _gateway(reply)
    gateway.model_request_budget = _proof
    result = gateway.complete_stream(
        [],
        on_text_delta=lambda _: None,
        invocation_policy=ModelInvocationPolicy(max_output_tokens=5),
    )
    assert result.assistant_message.content == "ok"
    assert len(gateway.worker_budget.settled) == 1
