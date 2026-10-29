"""Fresh authorization precedes every physical attempt, including retries/streams."""

from datetime import UTC, datetime

import httpx
import pytest
from agent_core.domain.execution_authority import ExecutionAuthorityResolutionError
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_integrations import OpenAICompatibleModelGateway
from agent_integrations.deepseek_responses import DeepSeekResponsesModelGateway


@pytest.mark.parametrize("wire", ["chat", "responses"])
@pytest.mark.parametrize("stream", [False, True])
def test_revocation_before_retry_never_reaches_transport(wire, stream):
    sends = []
    checks = []

    def send(request):
        sends.append(request)
        return httpx.Response(503, json={"error": {"message": "temporarily unavailable"}})

    def authorize(identity):
        checks.append(identity)
        if len(checks) > 1:
            raise ExecutionAuthorityResolutionError("revoked")

    client = httpx.Client(transport=httpx.MockTransport(send))
    kwargs = dict(
        base_url="https://api.example.test",
        api_key="test-only",
        model_name="deepseek-v4-flash",
        client=client,
    )
    gateway = (
        OpenAICompatibleModelGateway(provider_name="deepseek", **kwargs)
        if wire == "chat"
        else DeepSeekResponsesModelGateway(**kwargs)
    )
    gateway.authority_check = authorize
    messages = [
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.USER,
            content="test",
            created_at=datetime.now(UTC),
        )
    ]
    with pytest.raises(ExecutionAuthorityResolutionError, match="revoked"):
        if stream:
            gateway.complete_stream(messages, on_text_delta=lambda _: None)
        else:
            gateway.complete(messages)
    assert len(sends) == 1
    assert len(checks) == 2
    client.close()


def test_prepared_request_denial_sends_nothing():
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: pytest.fail("unexpected model send"))
    )
    gateway = OpenAICompatibleModelGateway(
        provider_name="deepseek",
        base_url="https://api.example.test",
        api_key="test-only",
        model_name="deepseek-v4-flash",
        client=client,
    )
    messages = [
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.USER,
            content="test",
            created_at=datetime.now(UTC),
        )
    ]
    from agent_core.domain.modeling import ModelInvocationPolicy, ModelRole, ModelToolChoice

    gateway._max_retries = 0
    prepared = gateway.prepare_text_request(
        messages,
        invocation_policy=ModelInvocationPolicy(
            role=ModelRole.REVIEWER, tool_choice=ModelToolChoice.NONE
        ),
    )

    def deny(_):
        raise ExecutionAuthorityResolutionError("revoked")

    gateway.authority_check = deny
    with pytest.raises(ExecutionAuthorityResolutionError):
        gateway.complete_prepared(prepared)
    client.close()
