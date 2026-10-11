"""Injected and actual provider-wire checks; no live model requests."""

import json
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from agent_core.application.coverage_checks import PublishedCoverageRunner
from agent_core.application.coverage_semantic import semantic_check
from agent_core.domain.coverage_contracts import CoverageRefusalReason as Reason
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_core.domain.coverage_validation import CoverageUnitKey
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCallMetadata,
    ModelCompletion,
    ModelRole,
    ModelToolChoice,
)
from agent_core.domain.tools import ToolCall
from agent_core.ports.model_gateway import ModelResponseRejectedError
from agent_integrations.coverage_model import SemanticCoverageModel
from agent_integrations.openai_compatible import OpenAICompatibleModelGateway

PROFILE = "deepseek-v4-pro-reviewer-v1"


def context():
    definition = semantic_check(PROFILE)
    check = definition.contract_check
    key = CoverageUnitKey(
        record_id="record-1",
        content_digest="a" * 64,
        check_id=check.id,
        check_version=check.version,
        definition_digest=check.definition_digest,
        kind="part",
        part_id="part-1",
        part_digest="b" * 64,
    )
    return definition, key, {"part-1": "source"}


def payload(key, outcome="clear"):
    return {
        "key": key.model_dump(mode="json"),
        "outcome": outcome,
        "categories": ["explicit_operational_or_harm_claim"] if outcome == "finding" else [],
        "quotes": [{"part_id": "part-1", "start": 0, "end": 6, "text": "source"}]
        if outcome == "finding"
        else [],
    }


def completion(content, *, profile=PROFILE, finish="stop", tools=()):
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content=content,
            created_at=datetime.now(UTC),
        ),
        tool_calls=tools,
        call_metadata=ModelCallMetadata(profile_id=profile, finish_reason=finish),
    )


class Gateway:
    def __init__(self, reply, events):
        self.reply, self.events, self.requests = reply, events, []

    def complete(self, messages, *, tools=(), invocation_policy=None):
        self.events.append("gateway")
        self.requests.append((messages, tools, invocation_policy))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def configured(reply, *, fail=None):
    events, recorded = [], []
    gateway = Gateway(reply, events)

    def authority():
        events.append("authority")
        if fail == f"authority-{events.count('authority')}":
            raise CoverageRefusedError(Reason.AUTHORITY_INVALID)

    def reserve():
        events.append("reserve")
        if fail == "reserve":
            raise CoverageRefusedError(Reason.BUDGET_EXCEEDED)

    def record(response):
        events.append("record")
        recorded.append(response)
        if fail == "record":
            raise RuntimeError("durable write failed")

    model = SemanticCoverageModel(
        gateway=gateway,
        model_profile=PROFILE,
        check_authority=authority,
        reserve_call=reserve,
        record_response=record,
    )
    return model, gateway, events, recorded


@pytest.mark.parametrize("outcome", ["finding", "clear"])
@pytest.mark.parametrize("finish", ["stop", "end_turn", "completed"])
def test_shared_runner_calls_reviewer_with_exact_data_and_order(outcome, finish):
    definition, key, bodies = context()
    reply = completion(json.dumps(payload(key, outcome)), finish=finish)
    model, gateway, events, recorded = configured(reply)
    result = PublishedCoverageRunner((definition,), model=model).run(key, bodies, prior=())
    assert result.outcome == outcome and result.key == key
    assert events == ["authority", "reserve", "authority", "gateway", "record", "authority"]
    assert recorded == [reply]
    messages, tools, policy = gateway.requests[0]
    assert [message.role for message in messages] == [MessageRole.SYSTEM, MessageRole.USER]
    assert messages[0].content == definition.instructions
    assert json.loads(messages[1].content) == {"key": key.model_dump(mode="json"), "bodies": bodies}
    assert tools == () and policy.role == ModelRole.REVIEWER
    assert policy.profile_id == PROFILE and policy.tool_choice == ModelToolChoice.NONE
    assert policy.max_output_tokens == 8192


@pytest.mark.parametrize(
    "failure",
    [
        "profile",
        "definition",
        "version",
        "key",
        "merge",
        "missing_part",
        "extra_part",
        "oversize",
        "nonstring",
    ],
)
def test_prevalidation_prevents_reservation_and_provider_call(failure):
    definition, key, bodies = context()
    model, gateway, events, recorded = configured(completion(json.dumps(payload(key))))
    if failure in {"profile", "definition", "version"}:
        field = {"profile": "model_profile", "definition": "instructions", "version": "version"}[
            failure
        ]
        definition = definition.model_copy(update={field: "changed"})
    elif failure == "key":
        key = key.model_copy(update={"definition_digest": "c" * 64})
    elif failure == "merge":
        key = key.model_copy(update={"kind": "record_merge", "part_id": None, "part_digest": None})
    elif failure == "missing_part":
        bodies = {}
    elif failure == "extra_part":
        bodies["part-2"] = ""
    elif failure == "oversize":
        bodies["part-1"] = "x" * 12001
    else:
        bodies["part-1"] = None
    with pytest.raises(CoverageRefusedError) as refused:
        model(definition, key, bodies)
    assert refused.value.reason == Reason.UNSUPPORTED
    assert not events and not gateway.requests and not recorded


@pytest.mark.parametrize(
    "failure",
    [
        "duplicate",
        "nested_duplicate",
        "nan",
        "infinity",
        "fence",
        "prose",
        "two_objects",
        "array",
        "malformed",
        "bytes",
        "utf8_bytes",
        "profile",
        "missing_profile",
        "finish",
        "missing_finish",
        "tools",
        "message_tools",
        "key",
        "quote",
        "extra",
        "unresolved",
        "retry",
        "repair",
    ],
)
def test_response_is_recorded_before_any_rejection(failure):
    definition, key, bodies = context()
    data = payload(key)
    text = json.dumps(data)
    if failure == "duplicate":
        text = text[:-1] + ', "outcome":"clear"}'
    elif failure == "nested_duplicate":
        text = text.replace(
            '"record_id": "record-1"', '"record_id":"record-1","record_id":"record-1"'
        )
    elif failure in {"nan", "infinity"}:
        text = text[:-1] + ',"confidence":' + ("NaN" if failure == "nan" else "Infinity") + "}"
    elif failure == "fence":
        text = "```json\n" + text + "\n```"
    elif failure == "prose":
        text = "Result: " + text
    elif failure == "two_objects":
        text += text
    elif failure == "array":
        text = "[" + text + "]"
    elif failure == "malformed":
        text = "{"
    elif failure == "bytes":
        text = text[:-1] + " " * 65536 + "}"
    elif failure == "utf8_bytes":
        text = json.dumps({**data, "extra": "字" * 22000}, ensure_ascii=False)
    elif failure == "key":
        data["key"]["record_id"] = "other"
        text = json.dumps(data)
    elif failure == "quote":
        data = payload(key, "finding")
        data["quotes"][0]["text"] = "invent"
        text = json.dumps(data)
    elif failure == "extra":
        text = json.dumps({**data, "confidence": 0.99})
    elif failure == "unresolved":
        text = json.dumps(payload(key, "unresolved"))
    reply = completion(
        text,
        profile="other"
        if failure == "profile"
        else None
        if failure == "missing_profile"
        else PROFILE,
        finish="length" if failure == "finish" else None if failure == "missing_finish" else "stop",
    )
    tool = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="files.read",
        arguments={},
        created_at=datetime.now(UTC),
    )
    if failure == "tools":
        reply = replace(reply, tool_calls=(tool,))
    elif failure == "message_tools":
        reply = replace(
            reply,
            assistant_message=reply.assistant_message.model_copy(update={"tool_calls": (tool,)}),
        )
    elif failure in {"retry", "repair"}:
        reply = replace(
            reply,
            call_metadata=replace(
                reply.call_metadata,
                **{"retry_count" if failure == "retry" else "response_repair_count": 1},
            ),
        )
    model, gateway, events, recorded = configured(reply)
    with pytest.raises(CoverageRefusedError) as refused:
        model(definition, key, bodies)
    expected = Reason.UNRESOLVED_REVIEW if failure == "unresolved" else Reason.UNSUPPORTED
    assert refused.value.reason == expected
    assert recorded == [reply] and len(gateway.requests) == 1
    assert events.index("record") > events.index("gateway")


@pytest.mark.parametrize(
    "failure,reason,calls,records",
    [
        ("authority-1", Reason.AUTHORITY_INVALID, 0, 0),
        ("reserve", Reason.BUDGET_EXCEEDED, 0, 0),
        ("authority-2", Reason.AUTHORITY_INVALID, 0, 0),
        ("authority-3", Reason.AUTHORITY_INVALID, 1, 1),
        ("record", Reason.UNRESOLVED_FAILURE, 1, 1),
    ],
)
def test_callback_failures_refuse_without_retry(failure, reason, calls, records):
    definition, key, bodies = context()
    model, gateway, events, recorded = configured(
        completion(json.dumps(payload(key))), fail=failure
    )
    with pytest.raises(CoverageRefusedError) as refused:
        model(definition, key, bodies)
    assert refused.value.reason == reason
    assert len(gateway.requests) == calls and len(recorded) == records


def test_provider_error_is_not_retried():
    definition, key, bodies = context()
    model, gateway, events, recorded = configured(RuntimeError("provider failed"))
    with pytest.raises(CoverageRefusedError):
        model(definition, key, bodies)
    assert len(gateway.requests) == 1 and not recorded


@pytest.mark.parametrize("profile", [None, "", " padded "])
def test_constructor_requires_valid_explicit_profile(profile):
    with pytest.raises(ValueError):
        SemanticCoverageModel(
            gateway=Gateway(None, []),
            model_profile=profile,
            check_authority=lambda: None,
            reserve_call=lambda: None,
            record_response=lambda response: None,
        )


def test_key_extra_storage_is_rejected_before_reservation():
    definition, key, bodies = context()
    model, gateway, events, recorded = configured(completion(json.dumps(payload(key))))
    object.__setattr__(key, "__pydantic_extra__", {"unknown": True})
    with pytest.raises(CoverageRefusedError) as refused:
        model(definition, key, bodies)
    assert refused.value.reason == Reason.UNSUPPORTED
    assert not events and not gateway.requests and not recorded


def test_response_utf8_limit_is_checked_before_json_parsing(monkeypatch):
    definition, key, bodies = context()
    reply = completion(json.dumps({"extra": "字" * 22000}, ensure_ascii=False))
    model, gateway, events, recorded = configured(reply)

    def unexpected_parse(*args, **kwargs):
        raise AssertionError("oversized UTF-8 response must never be parsed")

    monkeypatch.setattr("agent_integrations.coverage_model.json.loads", unexpected_parse)
    with pytest.raises(CoverageRefusedError) as refused:
        model(definition, key, bodies)
    assert refused.value.reason == Reason.UNSUPPORTED and recorded == [reply]


@pytest.mark.parametrize("role", [MessageRole.USER, MessageRole.SYSTEM])
def test_forged_completion_role_is_recorded_then_refused(role):
    definition, key, bodies = context()
    reply = completion(json.dumps(payload(key)))
    forged = reply.assistant_message.model_copy(update={"role": role})
    # Bypass ModelCompletion's constructor to exercise the acceptance boundary.
    object.__setattr__(reply, "assistant_message", forged)
    model, gateway, events, recorded = configured(reply)
    with pytest.raises(CoverageRefusedError) as refused:
        model(definition, key, bodies)
    assert refused.value.reason == Reason.UNSUPPORTED
    assert recorded == [reply] and len(gateway.requests) == 1


def test_callback_mutations_cannot_change_frozen_instructions_or_source():
    definition, key, bodies = context()
    instructions = definition.instructions
    reply = completion(json.dumps(payload(key, "finding")))
    gateway, recorded = Gateway(reply, []), []

    def reserve():
        object.__setattr__(definition, "instructions", "injected caller instructions")
        bodies["part-1"] = "invent"

    model = SemanticCoverageModel(
        gateway=gateway,
        model_profile=PROFILE,
        check_authority=lambda: None,
        reserve_call=reserve,
        record_response=recorded.append,
    )
    result = model(definition, key, bodies)
    messages, tools, policy = gateway.requests[0]
    assert messages[0].content == instructions
    assert json.loads(messages[1].content)["bodies"] == {"part-1": "source"}
    assert result.quotes[0].text == "source" and recorded == [reply]


def test_real_openai_compatible_wire_policy_and_usage():
    definition, key, bodies = context()
    requests, recorded = [], []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-pro",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": json.dumps(payload(key))},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        gateway = OpenAICompatibleModelGateway(
            provider_name="deepseek",
            base_url="https://mock.invalid",
            api_key="test-only",
            model_name="deepseek-v4-pro",
            max_retries=0,
            client=client,
        )
        model = SemanticCoverageModel(
            gateway=gateway,
            model_profile=PROFILE,
            check_authority=lambda: None,
            reserve_call=lambda: None,
            record_response=recorded.append,
        )
        assert model(definition, key, bodies).outcome == "clear"
    assert len(requests) == 1 and requests[0]["model"] == "deepseek-v4-pro"
    assert requests[0]["max_tokens"] == 8192 and "tools" not in requests[0]
    assert [message["role"] for message in requests[0]["messages"]] == ["system", "user"]
    assert recorded[0].call_metadata.profile_id == PROFILE
    assert recorded[0].call_metadata.role == "reviewer"
    assert recorded[0].call_metadata.tool_choice == "none"
    assert recorded[0].call_metadata.usage.total_tokens == 30


@pytest.mark.parametrize("wire_role", ["user", "system", None, 1, "missing"])
def test_real_gateway_rejects_wire_role_before_adapter_acceptance(wire_role):
    definition, key, bodies = context()
    requests, recorded = [], []

    def handle(request):
        requests.append(request)
        message = {"content": json.dumps(payload(key))}
        if wire_role != "missing":
            message["role"] = wire_role
        return httpx.Response(
            200,
            json={
                "choices": [{"message": message, "finish_reason": "stop"}],
                "usage": {"total_tokens": 30},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        gateway = OpenAICompatibleModelGateway(
            provider_name="deepseek",
            base_url="https://mock.invalid",
            api_key="test-only",
            model_name="deepseek-v4-pro",
            max_retries=0,
            client=client,
        )
        model = SemanticCoverageModel(
            gateway=gateway,
            model_profile=PROFILE,
            check_authority=lambda: None,
            reserve_call=lambda: None,
            record_response=recorded.append,
        )
        with pytest.raises(CoverageRefusedError) as refused:
            model(definition, key, bodies)
    assert refused.value.reason == Reason.UNRESOLVED_FAILURE
    assert isinstance(refused.value.__cause__, ModelResponseRejectedError)
    assert len(requests) == 1 and not recorded
