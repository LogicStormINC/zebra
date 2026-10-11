import copy
import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import httpx
import pytest
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelInvocationPolicy,
    ModelRole,
    ModelToolChoice,
    ModelToolDefinition,
)
from agent_core.ports.model_gateway import ModelResponseRejectedError
from agent_integrations.coverage_model_request import PreparedModelRequest
from agent_integrations.deepseek_profiles import DeepSeekProfileRouter
from agent_integrations.model_errors import ModelProviderError
from agent_integrations.openai_compatible import OpenAICompatibleModelGateway
from agent_integrations.request_metadata import _canonical_json, build_request_metadata

POLICY = ModelInvocationPolicy(
    role=ModelRole.REVIEWER,
    tool_choice=ModelToolChoice.NONE,
    max_output_tokens=8192,
    profile_id="deepseek-v4-pro-reviewer-v1",
)


class CountingRouter(DeepSeekProfileRouter):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def resolve(self, policy, *, has_tools):
        self.calls += 1
        return super().resolve(policy, has_tools=has_tools)


def message(content="source 世界", **kwargs):
    return SessionMessage(
        message_id=new_message_id(),
        created_at=datetime.now(UTC),
        role=MessageRole.USER,
        content=content,
        **kwargs,
    )


def response():
    return httpx.Response(
        200,
        json={
            "id": "completion-1",
            "model": "deepseek-v4-pro",
            "choices": [
                {"message": {"role": "assistant", "content": "checked"}, "finish_reason": "stop"}
            ],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 7,
                "total_tokens": 19,
                "prompt_cache_hit_tokens": 4,
                "prompt_cache_miss_tokens": 8,
                "completion_tokens_details": {"reasoning_tokens": 3},
            },
        },
    )


def gateway(handler, **kwargs):
    return OpenAICompatibleModelGateway(
        provider_name="deepseek",
        base_url="https://model.example/v1",
        api_key="private-key",
        model_name="legacy-model",
        max_retries=kwargs.pop("max_retries", 0),
        client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True),
        **kwargs,
    )


def test_exact_wire_metadata_usage_and_single_resolution():
    requests = []
    router = CountingRouter()
    model = gateway(lambda req: requests.append(req) or response(), deepseek_router=router)
    messages = [message(metadata={"untrusted": "before"})]
    prepared = model.prepare_text_request(messages, invocation_policy=POLICY)
    assert router.calls == 1
    original = prepared.body
    messages[0].metadata["untrusted"] = "after"
    object.__setattr__(messages[0], "content", "changed")
    messages.clear()
    result = model.complete_prepared(prepared)
    assert router.calls == 1
    assert len(requests) == 1
    assert requests[0].content == original
    assert hashlib.sha256(requests[0].content).hexdigest() == prepared.request_digest
    assert str(requests[0].url) == prepared.endpoint
    assert requests[0].headers["Authorization"] == "Bearer private-key"
    assert "private-key" not in repr(prepared)
    assert "tools" not in json.loads(original)
    assert json.loads(original)["stream"] is False
    assert prepared.request_metadata == build_request_metadata(
        json.loads(original), prepared.resolved
    )
    for name in vars(prepared.request_metadata):
        assert getattr(result.call_metadata, name) == getattr(prepared.request_metadata, name)
    assert result.call_metadata.profile_id == POLICY.profile_id
    assert result.call_metadata.requested_model == "deepseek-v4-pro"
    assert result.call_metadata.retry_count == 0
    assert result.call_metadata.usage.input_tokens == 12
    assert result.call_metadata.usage.output_tokens == 7
    assert result.call_metadata.usage.total_tokens == 19
    assert result.call_metadata.usage.reasoning_tokens == 3
    assert result.call_metadata.usage.prompt_cache_hit_tokens == 4
    assert result.call_metadata.usage.prompt_cache_miss_tokens == 8
    with pytest.raises(ValueError, match="consumed"):
        model.complete_prepared(prepared)
    assert len(requests) == 1


def test_same_semantic_wire_has_stable_digest_across_preparations_and_gateways():
    router = CountingRouter()
    model = gateway(lambda req: response(), deepseek_router=router)
    first = model.prepare_text_request([message()], invocation_policy=POLICY)
    second = model.prepare_text_request([message()], invocation_policy=POLICY)
    other = gateway(lambda req: response()).prepare_text_request(
        [message()], invocation_policy=POLICY
    )
    assert first is not second
    assert first.body == second.body == other.body
    assert first.request_digest == second.request_digest == other.request_digest
    assert router.calls == 2
    model.complete_prepared(first)
    model.complete_prepared(second)
    assert router.calls == 2
    with pytest.raises(FrozenInstanceError):
        first.body = b"{}"


@pytest.mark.parametrize(
    "change",
    [
        "body",
        "metadata",
        "profile",
        "resolved",
        "endpoint",
        "provider",
        "default_model",
        "raw_metadata",
        "raw_profile",
        "raw_resolved",
        "extra_metadata",
        "raw_string_role",
    ],
)
def test_mutation_refused_before_http(change):
    requests = []
    model = gateway(lambda req: requests.append(req) or response())
    prepared = model.prepare_text_request([message()], invocation_policy=POLICY)
    if change == "body":
        object.__setattr__(prepared, "body", b"{}")
    elif change == "metadata":
        object.__setattr__(prepared.request_metadata, "request_hash", "forged")
    elif change == "profile":
        object.__setattr__(prepared.resolved.profile.context_window, "context_tokens", 1)
    elif change == "resolved":
        object.__setattr__(prepared.resolved, "max_output_tokens", 1)
    elif change.startswith("raw_") and change != "raw_string_role":
        field = {
            "raw_metadata": "request_metadata",
            "raw_profile": "profile",
            "raw_resolved": "resolved",
        }[change]
        parent = prepared.resolved if field == "profile" else prepared
        raw = dict(vars(getattr(parent, field)))
        object.__setattr__(parent, field, raw)
    elif change == "raw_string_role":
        object.__setattr__(prepared.resolved, "role", "reviewer")
    elif change == "extra_metadata":
        object.__setattr__(prepared.request_metadata, "forged", True)
    else:
        object.__setattr__(prepared, change, "forged")
    with pytest.raises(ValueError):
        model.complete_prepared(prepared)
    assert requests == []


@pytest.mark.parametrize("copy_kind", ["construct", "replace", "copy", "deepcopy", "raw"])
def test_forged_identity_refused(copy_kind):
    requests = []
    model = gateway(lambda req: requests.append(req) or response())
    prepared = model.prepare_text_request([message()], invocation_policy=POLICY)
    if copy_kind == "construct":
        forged = PreparedModelRequest(**vars(prepared))
    elif copy_kind == "replace":
        forged = replace(prepared)
    elif copy_kind == "raw":
        forged = object.__new__(PreparedModelRequest)
        forged.__dict__.update(prepared.__dict__)
    else:
        forged = getattr(copy, copy_kind)(prepared)
    with pytest.raises(ValueError):
        model.complete_prepared(forged)
    assert requests == []


@pytest.mark.parametrize(
    "attribute,value",
    [
        ("_base_url", "https://other.example"),
        ("_provider_name", "other"),
        ("_model_name", "other"),
        ("_api_key", "replacement-key"),
        ("_max_retries", 1),
        ("_timeout_s", 42),
        ("_deepseek_router", DeepSeekProfileRouter()),
        ("_client", None),
    ],
)
def test_changed_configuration_refused(attribute, value):
    requests = []
    model = gateway(lambda req: requests.append(req) or response())
    prepared = model.prepare_text_request([message()], invocation_policy=POLICY)
    setattr(model, attribute, value)
    with pytest.raises(ValueError):
        model.complete_prepared(prepared)
    assert requests == []


def test_router_mapping_mutation_and_foreign_gateway_refused():
    requests = []
    router = DeepSeekProfileRouter()
    model = gateway(lambda req: requests.append(req) or response(), deepseek_router=router)
    prepared = model.prepare_text_request([message()], invocation_policy=POLICY)
    foreign = gateway(lambda req: requests.append(req) or response())
    with pytest.raises(ValueError):
        foreign.complete_prepared(prepared)
    router._role_profiles[ModelRole.REVIEWER] = "deepseek-v4-pro-reviewer-v1"
    with pytest.raises(ValueError):
        model.complete_prepared(prepared)
    assert requests == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"stream": True},
        {"strict_tools": True},
        {"tools": (ModelToolDefinition("echo", "Echo", {"type": "object", "properties": {}}),)},
        {"invocation_policy": replace(POLICY, role=ModelRole.EXECUTOR)},
        {"invocation_policy": replace(POLICY, tool_choice=ModelToolChoice.AUTO)},
        {"invocation_policy": replace(POLICY, profile_id="unknown")},
        {"invocation_policy": replace(POLICY, profile_id="deepseek-v4-pro-planner-v1")},
        {"invocation_policy": replace(POLICY, max_output_tokens=1_000_000)},
    ],
)
def test_unsupported_preparation_refused(kwargs):
    requests = []
    model = gateway(lambda req: requests.append(req) or response())
    options = {"invocation_policy": POLICY, **kwargs}
    with pytest.raises(ValueError):
        model.prepare_text_request([message()], **options)
    assert requests == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("role", MessageRole.TOOL),
        ("tool_call_id", "call-1"),
        ("provider_image_data_urls", ("data:image/png;base64,eA==",)),
        ("tool_calls", (object(),)),
        ("content", {"image_url": "https://image.example"}),
    ],
)
def test_nontext_or_tool_messages_refused(field, value):
    requests = []
    model = gateway(lambda req: requests.append(req) or response())
    source = message().model_copy(update={field: value})
    with pytest.raises(ValueError):
        model.prepare_text_request([source], invocation_policy=POLICY)
    assert requests == []


@pytest.mark.parametrize("retries", [-1, 1, 2])
def test_retry_configuration_refused_before_resolve_or_http(retries):
    requests = []
    router = CountingRouter()
    model = gateway(
        lambda req: requests.append(req) or response(), max_retries=retries, deepseek_router=router
    )
    with pytest.raises(ValueError):
        model.prepare_text_request([message()], invocation_policy=POLICY)
    assert router.calls == 0
    assert requests == []


def test_unresolved_provider_refused():
    model = OpenAICompatibleModelGateway(
        provider_name="openai",
        base_url="https://model.example",
        api_key="private-key",
        model_name="unknown",
        max_retries=0,
    )
    with pytest.raises(ValueError):
        model.prepare_text_request([message()], invocation_policy=POLICY)


@pytest.mark.parametrize("status", [302, 307, 429, 503])
def test_redirects_and_provider_errors_are_single_shot(status):
    requests = []

    def handle(req):
        requests.append(req)
        return httpx.Response(status, headers={"Location": "https://other.example/next"})

    model = gateway(handle)
    prepared = model.prepare_text_request([message()], invocation_policy=POLICY)
    with pytest.raises(ModelProviderError) as failure:
        model.complete_prepared(prepared)
    assert not failure.value.retryable
    assert failure.value.retry_count == 0
    assert len(requests) == 1
    with pytest.raises(ValueError):
        model.complete_prepared(prepared)
    assert len(requests) == 1


@pytest.mark.parametrize("kind", ["transport", "json", "shape", "choices", "truncated"])
def test_transient_and_malformed_responses_do_not_retry(kind):
    requests = []

    def handle(req):
        requests.append(req)
        if kind == "transport":
            raise httpx.ReadTimeout("timeout", request=req)
        if kind == "json":
            return httpx.Response(200, content=b"{bad")
        if kind == "shape":
            return httpx.Response(200, json=[])
        if kind == "choices":
            return httpx.Response(200, json={"choices": []})
        payload = response().json()
        payload["choices"][0]["finish_reason"] = "length"
        return httpx.Response(200, json=payload)

    model = gateway(handle)
    prepared = model.prepare_text_request([message()], invocation_policy=POLICY)
    with pytest.raises((ModelProviderError, ModelResponseRejectedError)) as failure:
        model.complete_prepared(prepared)
    assert not failure.value.retryable
    assert len(requests) == 1
    with pytest.raises(ValueError):
        model.complete_prepared(prepared)
    assert len(requests) == 1


def test_canonical_serialization_matches_frozen_bytes():
    model = gateway(lambda req: response())
    prepared = model.prepare_text_request([message()], invocation_policy=POLICY)
    assert _canonical_json(json.loads(prepared.body)) == prepared.body


def test_builder_is_called_once_and_transport_cannot_mutate_parser_inputs(monkeypatch):
    requests = []
    builds = []

    def handle(req):
        requests.append(req)
        object.__setattr__(prepared.request_metadata, "request_hash", "during-http")
        object.__setattr__(prepared.resolved.profile, "profile_id", "during-http")
        return response()

    model = gateway(handle)
    builder = model._request_body

    def build(*args, **kwargs):
        builds.append(True)
        return builder(*args, **kwargs)

    monkeypatch.setattr(model, "_request_body", build)
    prepared = model.prepare_text_request([message()], invocation_policy=POLICY)
    digest = prepared.request_digest
    completion = model.complete_prepared(prepared)
    assert builds == [True]
    assert len(requests) == 1
    assert completion.call_metadata.request_hash == digest
    assert completion.call_metadata.profile_id == POLICY.profile_id


@pytest.mark.parametrize("kind", ["none", "unknown", "raw_role", "raw_profile"])
def test_unsupported_resolution_refused_before_http(kind):
    requests = []

    class UnsupportedRouter(DeepSeekProfileRouter):
        def resolve(self, policy, *, has_tools):
            resolved = copy.deepcopy(super().resolve(policy, has_tools=has_tools))
            if kind == "none":
                return None
            if kind == "unknown":
                object.__setattr__(resolved.profile, "profile_id", "unknown")
            elif kind == "raw_role":
                object.__setattr__(resolved, "role", "reviewer")
            else:
                object.__setattr__(resolved.profile, "roles", {ModelRole.REVIEWER})
            return resolved

    model = gateway(
        lambda req: requests.append(req) or response(), deepseek_router=UnsupportedRouter()
    )
    with pytest.raises(ValueError):
        model.prepare_text_request([message()], invocation_policy=POLICY)
    assert requests == []


def test_ordinary_complete_keeps_supplied_client_redirect_behavior():
    requests = []

    def handle(req):
        requests.append(req)
        if len(requests) == 1:
            return httpx.Response(307, headers={"Location": "https://model.example/redirect"})
        return response()

    model = gateway(handle)
    assert (
        model.complete([message()], invocation_policy=POLICY).assistant_message.content == "checked"
    )
    assert len(requests) == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_output_tokens", False),
        ("max_output_tokens", True),
        ("max_output_tokens", 0),
        ("max_output_tokens", 0.0),
        ("max_output_tokens", 1.0),
        ("max_output_tokens", -1),
        ("max_output_tokens", "8192"),
        ("role", "reviewer"),
        ("thinking_mode", "auto"),
        ("reasoning_effort", "high"),
        ("tool_choice", "none"),
        ("profile_id", False),
        ("profile_id", 0),
        ("profile_id", ""),
        ("profile_id", " "),
        ("extra", True),
    ],
)
@pytest.mark.parametrize("construction", ["setattr", "rawcopy"])
def test_raw_policy_refused_before_lossy_resolution(field, value, construction):
    requests = []
    router = CountingRouter()
    model = gateway(lambda req: requests.append(req) or response(), deepseek_router=router)
    policy = copy.deepcopy(POLICY)
    if construction == "rawcopy":
        policy = object.__new__(ModelInvocationPolicy)
        policy.__dict__.update(vars(POLICY))
    object.__setattr__(policy, field, value)
    with pytest.raises(ValueError):
        model.prepare_text_request([message()], invocation_policy=policy)
    assert router.calls == 0
    assert requests == []


@pytest.mark.parametrize("limit", [None, 1, 8192, 393216])
def test_legitimate_optional_and_integer_policy_limits(limit):
    model = gateway(lambda req: response())
    prepared = model.prepare_text_request(
        [message()],
        invocation_policy=replace(POLICY, max_output_tokens=limit),
    )
    assert json.loads(prepared.body)["max_tokens"] == (393216 if limit is None else limit)


class ReplayAuth(httpx.Auth):
    def auth_flow(self, request):
        response = yield request
        if response.status_code == 503:
            yield request


@pytest.mark.parametrize("capability", ["auth", "request_hook", "response_hook", "params"])
@pytest.mark.parametrize("after_prepare", [False, True])
def test_prepared_client_capability_and_drift_refusal(capability, after_prepare):
    requests = []
    hooks = []
    model = gateway(lambda req: requests.append(req) or response())
    client = model._client
    if after_prepare:
        prepared = model.prepare_text_request([message()], invocation_policy=POLICY)
    if capability == "auth":
        client.auth = ReplayAuth()
    elif capability == "params":
        client.params = {"drift": "yes"}
    elif capability == "request_hook":

        def rewrite(request):
            hooks.append(True)
            request.stream = httpx.ByteStream(b'{"changed":true}')

        client.event_hooks["request"].append(rewrite)
    else:
        client.event_hooks["response"].append(lambda response: hooks.append(True))
    with pytest.raises(ValueError):
        if after_prepare:
            model.complete_prepared(prepared)
        else:
            model.prepare_text_request([message()], invocation_policy=POLICY)
    assert requests == []
    assert hooks == []


@pytest.mark.parametrize("stream", [False, True])
def test_ordinary_auth_hooks_and_params_remain_active(stream):
    requests = []
    hook_calls = []

    def handle(request):
        requests.append((str(request.url), b"".join(request.stream)))
        if len(requests) == 1:
            return httpx.Response(503)
        if stream:
            chunk = {
                "id": "completion-1",
                "model": "deepseek-v4-pro",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": "checked"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 12},
            }
            return httpx.Response(200, text="data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n")
        return response()

    def rewrite(request):
        hook_calls.append(True)
        request.stream = httpx.ByteStream(b'{"changed":true}')

    model = gateway(handle)
    model._client.auth = ReplayAuth()
    model._client.params = {"ordinary": "yes"}
    model._client.event_hooks["request"].append(rewrite)
    if stream:
        result = model.complete_stream(
            [message()],
            invocation_policy=POLICY,
            on_text_delta=lambda delta: None,
        )
    else:
        result = model.complete([message()], invocation_policy=POLICY)
    assert result.assistant_message.content == "checked"
    assert len(requests) == len(hook_calls) == 2
    assert all(url.endswith("?ordinary=yes") for url, body in requests)
    assert all(body == b'{"changed":true}' for url, body in requests)


@pytest.mark.parametrize(
    "kind", ["subclass_client", "subclass_mock", "subclass_http", "custom", "mount"]
)
def test_unknown_client_transport_or_mount_refused(kind):
    requests = []

    class CustomTransport(httpx.BaseTransport):
        def handle_request(self, request):
            requests.extend([request, request])
            return response()

    class DerivedMock(httpx.MockTransport):
        pass

    class DerivedHTTP(httpx.HTTPTransport):
        pass

    class DerivedClient(httpx.Client):
        pass

    transport = httpx.MockTransport(lambda req: requests.append(req) or response())
    if kind == "subclass_mock":
        transport = DerivedMock(lambda req: requests.append(req) or response())
    elif kind == "subclass_http":
        transport = DerivedHTTP(retries=0)
    elif kind == "custom":
        transport = CustomTransport()
    client_type = DerivedClient if kind == "subclass_client" else httpx.Client
    client = client_type(transport=transport)
    if kind == "mount":
        client._mounts[object()] = CustomTransport()
    model = gateway(lambda req: requests.append(req) or response())
    model._client = client
    with pytest.raises(ValueError):
        model.prepare_text_request([message()], invocation_policy=POLICY)
    assert requests == []


@pytest.mark.parametrize("drift", ["transport", "mount", "handler", "headers", "timeout", "method"])
def test_prepared_supported_client_configuration_drift_refused(drift):
    requests = []
    model = gateway(lambda req: requests.append(req) or response())
    prepared = model.prepare_text_request([message()], invocation_policy=POLICY)
    client = model._client
    if drift == "transport":
        client._transport = httpx.MockTransport(lambda req: requests.append(req) or response())
    elif drift == "mount":
        client._mounts[object()] = client._transport
    elif drift == "handler":
        client._transport.handler = lambda req: requests.append(req) or response()
    elif drift == "headers":
        client.headers["X-Drift"] = "yes"
    elif drift == "method":
        client.build_request = lambda *args, **kwargs: pytest.fail("must reject overridden method")
    else:
        client.timeout = httpx.Timeout(42)
    with pytest.raises(ValueError):
        model.complete_prepared(prepared)
    assert requests == []


@pytest.mark.parametrize("retries", [0, 2])
def test_installed_standard_http_transport_retry_configuration_without_http(retries):
    with httpx.Client(transport=httpx.HTTPTransport(retries=retries), trust_env=False) as client:
        model = gateway(lambda req: pytest.fail("unexpected HTTP"))
        model._client = client
        if retries:
            with pytest.raises(ValueError):
                model.prepare_text_request([message()], invocation_policy=POLICY)
        else:
            prepared = model.prepare_text_request([message()], invocation_policy=POLICY)
            client._transport._pool._retries = 2
            with pytest.raises(ValueError):
                model.complete_prepared(prepared)


def test_no_injected_client_prepares_without_http():
    model = gateway(lambda req: pytest.fail("unexpected HTTP"))
    model._client = None
    assert model.prepare_text_request([message()], invocation_policy=POLICY).request_digest


def test_pre_send_local_validation_rejects_invalid_wire_headers_before_http():
    requests = []
    model = gateway(lambda req: requests.append(req) or response())
    model._client.headers["Content-Length"] = "1"
    prepared = model.prepare_text_request([message()], invocation_policy=POLICY)
    with pytest.raises(ModelProviderError):
        model.complete_prepared(prepared)
    assert requests == []


@pytest.mark.parametrize(
    "userinfo",
    [
        "probe-user@",
        "probe-user:probe-pass@",
        "@",
        ":probe-pass@",
        "probe%2Duser:probe%2Dpass@",
    ],
)
def test_url_userinfo_refused_before_builder_without_credential_exposure(userinfo, monkeypatch):
    requests = []
    router = CountingRouter()
    model = gateway(lambda req: requests.append(req) or response(), deepseek_router=router)
    model._base_url = f"https://{userinfo}model.example/v1"
    monkeypatch.setattr(model, "_request_body", lambda *args, **kw: pytest.fail("builder called"))
    with pytest.raises(ValueError) as failure:
        model.prepare_text_request([message()], invocation_policy=POLICY)
    assert str(failure.value) == "unsupported prepared endpoint"
    assert failure.value.__cause__ is None
    assert router.calls == 0
    assert requests == []


def test_ordinary_url_userinfo_compatibility_preserved():
    requests = []
    model = gateway(lambda req: requests.append(req) or response())
    model._base_url = "https://probe-user:probe-pass@model.example/v1"
    model.complete([message()], invocation_policy=POLICY)
    assert len(requests) == 1
    assert requests[0].headers["Authorization"].startswith("Basic ")
