import json
import logging

import httpx
import pytest
from agent_integrations import (
    deepseek_responses,
    deepseek_responses_streaming,
    model_errors,
    openai_compatible,
    openai_streaming,
)
from agent_integrations.deepseek_responses import DeepSeekResponsesModelGateway
from agent_integrations.model_errors import ModelProviderError
from agent_integrations.openai_compatible import OpenAICompatibleModelGateway


@pytest.mark.parametrize("wire", ["chat", "responses"])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(
    "failure", ["ConnectTimeout", "ReadTimeout", "RemoteProtocolError", 503, 400]
)
def test_attempt_diagnostics_keep_failure_and_total_call_timing(
    wire,
    streaming,
    failure,
    monkeypatch,
    caplog,
):
    clock = [0.0]
    for module in (
        openai_compatible,
        deepseek_responses,
        openai_streaming,
        deepseek_responses_streaming,
        model_errors,
    ):
        monkeypatch.setattr(module, "perf_counter", lambda: clock[0], raising=False)
    requests = []
    terminal = (
        {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "private-answer"},
                    "finish_reason": "stop",
                }
            ]
        }
        if wire == "chat"
        else {
            "id": "resp-1",
            "status": "completed",
            "model": "deepseek-v4-flash",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": "private-answer"},
                    ],
                }
            ],
        }
    )

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            clock[0] += 0.5
            delta = (
                {"choices": [{"delta": {"content": "private-answer"}}]}
                if wire == "chat"
                else {
                    "type": "response.output_text.delta",
                    "sequence_number": 0,
                    "delta": "private-answer",
                }
            )
            yield f"data: {json.dumps(delta)}\n\n".encode()
            clock[0] += 0.25
            finish = (
                {"choices": [{"delta": {}, "finish_reason": "stop"}]}
                if wire == "chat"
                else {"type": "response.completed", "sequence_number": 1, "response": terminal}
            )
            yield f"data: {json.dumps(finish)}\n\ndata: [DONE]\n\n".encode()

    def handle(request):
        requests.append(request)
        if len(requests) == 1:
            clock[0] += 2
            if isinstance(failure, int):
                return httpx.Response(failure, text="private-error-body")
            raise getattr(httpx, failure)("private-exception-text", request=request)
        if streaming:
            return httpx.Response(200, stream=Stream())
        clock[0] += 0.75
        return httpx.Response(200, json=terminal)

    caplog.set_level(logging.INFO, logger="agent_integrations.model_errors")
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        kwargs = dict(
            base_url="https://private-host.example",
            api_key="private-api-key",
            model_name="deepseek-v4-flash",
            client=client,
        )
        gateway = (
            OpenAICompatibleModelGateway(provider_name="deepseek", **kwargs)
            if wire == "chat"
            else DeepSeekResponsesModelGateway(**kwargs)
        )
        if failure == 400:
            with pytest.raises(ModelProviderError):
                if streaming:
                    gateway.complete_stream([], on_text_delta=lambda _: None)
                else:
                    gateway.complete([])
        else:
            completion = (
                gateway.complete_stream([], on_text_delta=lambda _: None)
                if streaming
                else gateway.complete([])
            )
            assert completion.call_metadata.retry_count == 1
            assert completion.call_metadata.latency_ms == 2750
            if streaming:
                # Existing durable field remains successful-attempt-relative.
                assert completion.call_metadata.time_to_first_public_text_ms == 500
    records = [
        json.loads(r.getMessage().removeprefix("model_provider_attempt "))
        for r in caplog.records
        if r.name == "agent_integrations.model_errors"
    ]
    assert len(records) == len(requests) == (1 if failure == 400 else 2)
    first = records[0]
    assert first["attempt"] == 1
    assert first["outcome"] == "failed"
    assert first["attempt_latency_ms"] == first["call_elapsed_ms"] == 2000
    assert first["error_type"] == ("HTTPStatusError" if isinstance(failure, int) else failure)
    assert first["http_status"] == (failure if isinstance(failure, int) else None)
    assert first["normalized_error"] == (
        "invalid_request"
        if failure == 400
        else "provider_unavailable"
        if failure == 503
        else "transport_error"
    )
    if failure != 400:
        last = records[1]
        assert last["call_id"] == first["call_id"]
        assert last["attempt"] == 2
        assert last["outcome"] == "completed"
        assert last["attempt_latency_ms"] == 750
        assert last["call_elapsed_ms"] == 2750
        assert last["attempt_first_public_text_ms"] == (500 if streaming else None)
        assert last["call_to_successful_attempt_public_text_ms"] == (2500 if streaming else None)
    assert "private-" not in caplog.text


def test_failed_and_recovered_attempts_survive_default_warning_level(caplog):
    caplog.set_level(logging.WARNING, logger="agent_integrations.model_errors")
    model_errors.log_provider_attempt(
        "bounded-id", 1, 0, 0, error=httpx.ReadTimeout("private-detail")
    )
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING
