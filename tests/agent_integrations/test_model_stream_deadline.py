import httpx
import pytest
from agent_integrations import deepseek_responses_streaming, openai_streaming
from agent_integrations.model_errors import ModelProviderError


@pytest.mark.parametrize(
    "module,reader,times",
    [
        (
            deepseek_responses_streaming,
            deepseek_responses_streaming.read_deepseek_responses_stream,
            (0.0, 181.0),
        ),
        (openai_streaming, openai_streaming.read_openai_stream, (0.0, 181.0)),
    ],
)
def test_model_stream_stops_after_absolute_deadline(monkeypatch, module, reader, times):
    ticks = iter(times)
    monkeypatch.setattr(module, "perf_counter", lambda: next(ticks))
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="data: ignored\n\n")
        )
    ) as client:
        with pytest.raises(ModelProviderError, match="provider_stream_deadline_exceeded") as error:
            reader(
                client,
                url="https://example.com/responses",
                headers={},
                body={},
                on_text_delta=lambda _: None,
            )
    assert error.value.retryable
