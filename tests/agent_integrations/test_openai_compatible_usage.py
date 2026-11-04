import httpx
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_integrations import OpenAICompatibleModelGateway

from tests.agent_integrations.test_openai_compatible import (
    _created_at,
    _handle_basic_completion,
    _message_id,
)


def test_usage_observer_records_failed_and_successful_provider_attempts():
    observed = []
    captured = {}

    def handle(request):
        if len(observed) == 1:
            return httpx.Response(503, json={"error": {"message": "unavailable"}})
        return _handle_basic_completion(request, captured)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        gateway = OpenAICompatibleModelGateway(
            provider_name="deepseek",
            base_url="https://models.example",
            api_key="synthetic",
            model_name="deepseek-v4-flash",
            client=client,
        )
        gateway.usage_observer = lambda *entry: observed.append(entry)
        gateway.complete(
            [
                SessionMessage(
                    message_id=_message_id(),
                    role=MessageRole.USER,
                    content="hello",
                    created_at=_created_at(),
                )
            ]
        )
    first, failed, second, finished = observed
    assert first[0] != second[0]
    assert first[1:] == second[1:] == ("started", None)
    assert failed == (first[0], "finished", None)
    assert finished[:2] == (second[0], "finished")
    assert finished[2].total_tokens == 12
