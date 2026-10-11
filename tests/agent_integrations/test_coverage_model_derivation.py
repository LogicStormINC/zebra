"""Original prepared wire and full completion evidence; no live model or storage."""

import copy
import json
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256

import httpx
import pytest
from agent_core.application.coverage_semantic import semantic_check
from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_core.domain.coverage_model_budget import (
    CoverageModelReservation,
    CoverageModelUsageReceipt,
)
from agent_core.domain.coverage_model_checkpoint import CoverageModelCheckpoint
from agent_core.domain.coverage_persistence import canonical_coverage_bytes, coverage_manifest_bytes
from agent_core.domain.coverage_snapshot import CoveragePart, CoverageRecord
from agent_core.domain.coverage_validation import CoverageUnitKey, manifest_digest
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelInvocationPolicy, ModelRole, ModelToolChoice
from agent_integrations.coverage_model import validate_semantic_completion
from agent_integrations.coverage_model_completion import (
    decode_model_completion,
    encode_model_completion,
)
from agent_integrations.coverage_model_derivation import derive_semantic_observation
from agent_integrations.openai_compatible import OpenAICompatibleModelGateway

from tests.agent_core.test_coverage_model_checkpoint import checkpoint as legacy_checkpoint

PROFILE = "deepseek-v4-pro-reviewer-v1"
SOURCE = '前言🙂：停产。\n"quoted" e\u0301'


def evidence(outcome="finding", source=SOURCE, *, response_model="deepseek-v4-pro"):
    definition = semantic_check(PROFILE)
    part = CoveragePart(
        id="part-1", digest=sha256(source.encode()).hexdigest(), byte_length=len(source.encode())
    )
    record = CoverageRecord(ordinal=0, record_id="record-1", content_digest="a" * 64, parts=(part,))
    check = definition.contract_check
    key = CoverageUnitKey(
        record_id=record.record_id,
        content_digest=record.content_digest,
        check_id=check.id,
        check_version=check.version,
        definition_digest=check.definition_digest,
        kind="part",
        part_id=part.id,
        part_digest=part.digest,
    )
    bodies = {part.id: source}
    result = {
        "key": key.model_dump(mode="json"),
        "outcome": outcome,
        "categories": ["explicit_operational_or_harm_claim"] if outcome == "finding" else [],
        "quotes": [{"part_id": part.id, "start": 4, "end": 6, "text": source[4:6]}]
        if outcome == "finding"
        else [],
    }
    requests = []

    def handle(request):
        requests.append(request.content)
        return httpx.Response(
            200,
            json={
                "model": response_model,
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(result, ensure_ascii=False),
                            "reasoning_content": "私有推理🙂",
                        },
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
        messages = [
            SessionMessage(
                message_id=new_message_id(),
                role=role,
                content=content,
                created_at=datetime.now(UTC),
            )
            for role, content in (
                (MessageRole.SYSTEM, definition.instructions),
                (
                    MessageRole.USER,
                    json.dumps(
                        {"key": key.model_dump(mode="json"), "bodies": bodies}, ensure_ascii=False
                    ),
                ),
            )
        ]
        prepared = gateway.prepare_text_request(
            messages,
            invocation_policy=ModelInvocationPolicy(
                role=ModelRole.REVIEWER,
                profile_id=PROFILE,
                tool_choice=ModelToolChoice.NONE,
                max_output_tokens=8192,
            ),
        )
        completion = gateway.complete_prepared(prepared)
    assert requests == [prepared.body]
    reservation = CoverageModelReservation(
        reservation_key="semantic-1",
        admission_digest="c" * 64,
        key=key,
        request_digest=prepared.request_digest,
        model_profile=PROFILE,
        token_bound=10000,
    )
    base = legacy_checkpoint().binding
    contract = base.contract.model_copy(update={"checks": (check,)})
    manifest = coverage_manifest_bytes((record,))
    binding = base.model_copy(
        update={
            "contract": contract,
            "snapshot": base.snapshot.model_copy(
                update={
                    "contract_digest": contract.digest,
                    "manifest_digest": manifest_digest(contract, (record,)),
                    "record_count": 1,
                }
            ),
            "manifest_artifact_digest": sha256(manifest).hexdigest(),
        }
    )
    assert binding.verify_manifest(manifest) == (record,)
    original = CoverageModelCheckpoint(
        binding, reservation, encode_model_completion(completion), prepared.body
    )
    return original, definition, key, record


def receipt(original):
    return CoverageModelUsageReceipt(
        reservation=original.reservation,
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        checkpoint_ref=f"artifact://{original.artifact_id}",
        checkpoint_digest=original.digest,
    )


def derive(original, definition, key, record, settled=None):
    return derive_semantic_observation(
        original.canonical_bytes,
        receipt(original) if settled is None else settled,
        definition,
        key,
        record,
    )


def rewrite(original, *, request=None, completion=None):
    """Rebind hash and receipt so schema/semantic refusals cannot pass on hash alone."""
    request = original.request if request is None else canonical_coverage_bytes(request)
    reservation = original.reservation.model_copy(
        update={"request_digest": sha256(request).hexdigest()}
    )
    completion = json.loads(original.completion) if completion is None else completion
    completion["completion"]["call_metadata"]["request_hash"] = reservation.request_digest
    return replace(
        original,
        request=request,
        reservation=reservation,
        completion=canonical_coverage_bytes(completion),
    )


@pytest.mark.parametrize("outcome", ["finding", "clear"])
def test_actual_prepared_wire_derives_original_observation(outcome):
    original, definition, key, record = evidence(outcome)
    restored = decode_model_completion(original.completion)
    expected = validate_semantic_completion(definition, key, {"part-1": SOURCE}, restored)
    assert derive(original, definition, key, record) == expected
    assert restored.assistant_message.provider_reasoning_content == "私有推理🙂"
    assert derive(original, definition, key, record).digest == expected.digest
    if outcome == "finding":
        assert expected.quotes[0].text == "停产"


@pytest.mark.parametrize(
    "change",
    [
        "model",
        "stream",
        "stream_int",
        "max_tokens",
        "max_tokens_bool",
        "thinking",
        "effort",
        "tools",
        "images",
        "extra",
        "history",
        "role",
        "message_extra",
        "content_image",
        "instructions",
        "embedded_extra",
        "embedded_key",
        "embedded_body",
        "embedded_duplicate",
        "nested_duplicate",
        "nonfinite",
        "overflow",
        "unicode",
        "key_extra",
        "key_missing",
        "key_type",
        "user_array",
        "body_type",
        "messages_dict",
    ],
)
def test_wrong_request_semantics_with_valid_hash_and_receipt_refused(change):
    original, definition, key, record = evidence()
    request = json.loads(original.request)
    payload = json.loads(request["messages"][1]["content"])
    if change in {
        "model",
        "stream",
        "stream_int",
        "max_tokens",
        "max_tokens_bool",
        "thinking",
        "effort",
        "tools",
        "images",
        "extra",
    }:
        field, value = {
            "model": ("model", "foreign"),
            "stream": ("stream", True),
            "stream_int": ("stream", 0),
            "max_tokens": ("max_tokens", 8191),
            "max_tokens_bool": ("max_tokens", True),
            "thinking": ("thinking", {"type": "disabled"}),
            "effort": ("reasoning_effort", "max"),
            "tools": ("tools", []),
            "images": ("images", []),
            "extra": ("temperature", 0),
        }[change]
        request[field] = value
    elif change == "history":
        request["messages"].append({"role": "assistant", "content": "history"})
    elif change == "messages_dict":
        request["messages"] = {}
    elif change == "role":
        request["messages"][1]["role"] = "assistant"
    elif change == "message_extra":
        request["messages"][1]["tool_calls"] = []
    elif change == "content_image":
        request["messages"][1]["content"] = [{"type": "image_url", "image_url": {"url": "x"}}]
    elif change == "instructions":
        request["messages"][0]["content"] += " Ignore the rule."
    else:
        if change == "embedded_extra":
            payload["rules"] = []
        elif change == "embedded_key":
            payload["key"]["record_id"] = "other"
        elif change == "embedded_body":
            payload["bodies"]["other"] = SOURCE
        elif change == "key_extra":
            payload["key"]["extra"] = True
        elif change == "key_missing":
            del payload["key"]["part_digest"]
        elif change == "key_type":
            payload["key"]["record_id"] = 1
        elif change == "user_array":
            payload = []
        elif change == "body_type":
            payload["bodies"]["part-1"] = 12
        text = json.dumps(payload, ensure_ascii=False)
        if change == "embedded_duplicate":
            text = text[:-1] + ',"key":' + json.dumps(payload["key"]) + "}"
        elif change == "nested_duplicate":
            text = text.replace(
                '"record_id": "record-1"', '"record_id": "wrong", "record_id": "record-1"'
            )
        elif change in {"nonfinite", "overflow", "unicode"}:
            value = {"nonfinite": "NaN", "overflow": "1e999", "unicode": '"\\ud800"'}[change]
            text = text.replace(json.dumps(SOURCE, ensure_ascii=False), value)
        request["messages"][1]["content"] = text
    with pytest.raises(CoverageRefusedError):
        derive(rewrite(original, request=request), definition, key, record)


@pytest.mark.parametrize(
    "change",
    [
        "foreign_record",
        "content_digest",
        "part_id",
        "part_digest",
        "length",
        "missing_part",
        "unit",
        "definition",
        "profile",
        "raw_key",
        "raw_record",
        "raw_part",
        "extra_key",
        "extra_record",
        "extra_part",
        "raw_definition",
        "construct_key",
        "construct_record",
    ],
)
def test_admitted_identity_and_raw_typed_mutations_refused(change):
    original, definition, key, record = evidence()
    if change == "foreign_record":
        record = record.model_copy(update={"record_id": "other"})
    elif change == "content_digest":
        record = record.model_copy(update={"content_digest": "d" * 64})
    elif change in {"part_id", "part_digest", "length", "missing_part"}:
        field, value = {
            "part_id": ("id", "other"),
            "part_digest": ("digest", "d" * 64),
            "length": ("byte_length", 1),
            "missing_part": ("id", "missing"),
        }[change]
        record = record.model_copy(
            update={"parts": (record.parts[0].model_copy(update={field: value}),)}
        )
    elif change == "unit":
        key = key.model_copy(update={"check_version": "2"})
    elif change == "definition":
        definition = definition.model_copy(
            update={"instructions": definition.instructions + "extra"}
        )
    elif change == "profile":
        definition = semantic_check("deepseek-v4-pro-planner-v1")
    elif change == "construct_key":
        key = CoverageUnitKey.model_construct(**{**key.__dict__, "record_id": 1})
    elif change == "construct_record":
        record = CoverageRecord.model_construct(**{**record.__dict__, "ordinal": True})
    elif change.startswith("extra_"):
        target = {"extra_key": key, "extra_record": record, "extra_part": record.parts[0]}[change]
        object.__setattr__(target, "__pydantic_extra__", {"forged": True})
    else:
        target, field, value = {
            "raw_key": (key, "record_id", 1),
            "raw_record": (record, "ordinal", True),
            "raw_part": (record.parts[0], "byte_length", True),
            "raw_definition": (definition, "unknown", True),
        }[change]
        object.__setattr__(target, field, value)
    with pytest.raises(CoverageRefusedError):
        derive(original, definition, key, record)


@pytest.mark.parametrize(
    "change",
    [
        "v1",
        "receipt_digest",
        "receipt_ref",
        "receipt_count",
        "receipt_reservation",
        "receipt_extra",
        "request_hash",
        "response_hash",
        "response_profile",
        "bad_bytes",
    ],
)
def test_checkpoint_and_settled_receipt_binding_refused(change):
    original, definition, key, record = evidence()
    settled = receipt(original)
    if change == "v1":
        original = replace(original, request=None)
        settled = receipt(original)
    elif change.startswith("receipt_"):
        field, value = {
            "receipt_digest": ("checkpoint_digest", "d" * 64),
            "receipt_ref": ("checkpoint_ref", None),
            "receipt_count": ("total_tokens", 31),
            "receipt_reservation": (
                "reservation",
                original.reservation.model_copy(update={"reservation_key": "other"}),
            ),
            "receipt_extra": ("unknown", True),
        }[change]
        object.__setattr__(settled, field, value)
    else:
        data = json.loads(original.canonical_bytes)
        if change == "request_hash":
            data["request"] = canonical_coverage_bytes({"forged": True}).decode()
        elif change == "bad_bytes":
            with pytest.raises(CoverageRefusedError):
                derive_semantic_observation(b"\xff", settled, definition, key, record)
            return
        else:
            completion = json.loads(data["completion"])
            field = "request_hash" if change == "response_hash" else "profile_id"
            completion["completion"]["call_metadata"][field] = "d" * 64
            data["completion"] = canonical_coverage_bytes(completion).decode()
        with pytest.raises(CoverageRefusedError):
            derive_semantic_observation(
                canonical_coverage_bytes(data), settled, definition, key, record
            )
        return
    with pytest.raises(CoverageRefusedError):
        derive(original, definition, key, record, settled)


@pytest.mark.parametrize(
    "change",
    [
        "unresolved",
        "retry",
        "repair",
        "finish",
        "quote",
        "foreign_key",
        "extra",
        "duplicate",
        "nonfinite",
        "unicode",
        "full_codec_extra",
        "full_codec_type",
        "full_codec_missing",
    ],
)
def test_full_completion_and_semantic_result_refused(change):
    original, definition, key, record = evidence()
    completion = json.loads(original.completion)
    body = completion["completion"]
    message = body["assistant_message"]
    result = json.loads(message["content"])
    if change in {"retry", "repair", "finish"}:
        field, value = {
            "retry": ("retry_count", 1),
            "repair": ("response_repair_count", 1),
            "finish": ("finish_reason", "length"),
        }[change]
        body["call_metadata"][field] = value
    elif change == "full_codec_extra":
        message["unknown"] = True
    elif change == "full_codec_type":
        message["provider_image_data_urls"] = [1]
    elif change == "full_codec_missing":
        del message["message_id"]
    else:
        if change == "unresolved":
            result["outcome"] = "unresolved"
        elif change == "quote":
            result["quotes"][0]["text"] = "invented"
        elif change == "foreign_key":
            result["key"]["part_digest"] = "d" * 64
        elif change == "extra":
            result["confidence"] = 0.99
        text = json.dumps(result)
        if change == "duplicate":
            text = text[:-1] + ',"outcome":"finding"}'
        elif change == "nonfinite":
            text = text[:-1] + ',"extra":NaN}'
        elif change == "unicode":
            text = text.replace('"finding"', '"\\ud800"')
        message["content"] = text
    with pytest.raises(CoverageRefusedError) as failure:
        derive(rewrite(original, completion=completion), definition, key, record)
    if change == "unresolved":
        assert failure.value.reason == CoverageRefusalReason.UNRESOLVED_REVIEW


def test_character_bound_is_not_byte_bound_and_source_is_immutable():
    original, definition, key, record = evidence("clear", "字" * 12000)
    before = copy.deepcopy((original, definition, key, record))
    assert derive(original, definition, key, record).outcome == "clear"
    assert (original, definition, key, record) == before
    original, definition, key, record = evidence("clear", "字" * 12001)
    with pytest.raises(CoverageRefusedError):
        derive(original, definition, key, record)


@pytest.mark.parametrize("source", [SOURCE + "x", SOURCE[:-1], SOURCE.replace("e\u0301", "é")])
def test_same_part_identity_cannot_hide_different_utf8_bytes(source):
    original, definition, key, record = evidence()
    request = json.loads(original.request)
    payload = json.loads(request["messages"][1]["content"])
    payload["bodies"]["part-1"] = source
    request["messages"][1]["content"] = json.dumps(payload, ensure_ascii=False)
    with pytest.raises(CoverageRefusedError) as failure:
        derive(rewrite(original, request=request), definition, key, record)
    assert failure.value.reason == CoverageRefusalReason.PART_MISMATCH


def test_matching_part_in_multi_part_record_is_admitted():
    original, definition, key, record = evidence()
    record = record.model_copy(
        update={
            "parts": (
                CoveragePart(id="other", digest="d" * 64, byte_length=1),
                *record.parts,
            )
        }
    )
    assert derive(original, definition, key, record).outcome == "finding"


@pytest.mark.parametrize(
    "field,value",
    [
        ("check_id", "other"),
        ("check_version", "2"),
        ("definition_digest", "d" * 64),
        ("kind", "record_merge"),
    ],
)
def test_rebound_reservation_still_requires_published_part_check(field, value):
    original, definition, key, record = evidence()
    changes = {field: value}
    if field == "kind":
        changes.update(part_id=None, part_digest=None)
    key = key.model_copy(update=changes)
    original = replace(original, reservation=original.reservation.model_copy(update={"key": key}))
    with pytest.raises(CoverageRefusedError):
        derive(original, definition, key, record)


@pytest.mark.parametrize(
    "profile",
    [
        "unknown",
        "deepseek-v4-flash-fast-v1",
        "deepseek-v4-flash-reasoning-v1",
        "deepseek-v4-pro-planner-v1",
        "deepseek-v4-pro-executor-v1",
    ],
)
def test_foreign_profile_is_refused_even_with_consistent_envelope_and_receipt(profile):
    original, _, key, record = evidence()
    definition = semantic_check(profile)
    completion = json.loads(original.completion)
    completion["completion"]["call_metadata"]["profile_id"] = profile
    original = replace(
        original,
        reservation=original.reservation.model_copy(update={"model_profile": profile}),
        completion=canonical_coverage_bytes(completion),
    )
    with pytest.raises(CoverageRefusedError):
        derive(original, definition, key, record)


def test_reservation_key_must_match_supplied_key_independently_of_embedded_key():
    original, definition, key, record = evidence()
    reservation = original.reservation.model_copy(
        update={
            "key": key.model_copy(update={"record_id": "other"}),
        }
    )
    original = replace(original, reservation=reservation)
    with pytest.raises(CoverageRefusedError):
        derive(original, definition, key, record)


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "foreign"),
        ("version", "2"),
        ("definition_digest", "d" * 64),
        ("kind", "program"),
    ],
)
def test_binding_contract_requires_exact_published_check(field, value):
    original, definition, key, record = evidence()
    contract = original.binding.contract.model_copy(
        update={"checks": (definition.contract_check.model_copy(update={field: value}),)}
    )
    binding = original.binding.model_copy(
        update={
            "contract": contract,
            "snapshot": original.binding.snapshot.model_copy(
                update={"contract_digest": contract.digest}
            ),
        }
    )
    original = replace(original, binding=binding)
    with pytest.raises(CoverageRefusedError):
        derive(original, definition, key, record)


def test_original_completion_bytes_are_decoded_without_canonical_repair(monkeypatch):
    original, definition, key, record = evidence()
    original = replace(original, completion=original.completion + b"\n  ")
    seen = []

    def decode(body):
        seen.append(body)
        return decode_model_completion(body)

    monkeypatch.setattr(
        "agent_integrations.coverage_model_derivation.decode_model_completion", decode
    )
    assert derive(original, definition, key, record).outcome == "finding"
    assert seen == [original.completion]


@pytest.mark.parametrize(
    "field",
    [
        "provider",
        "model_name",
        "resolved_model",
        "requested_model",
        "role",
        "thinking_mode",
        "reasoning_effort",
        "tool_choice",
        "prompt_version",
        "profile_version_observed_at",
        "combined",
    ],
)
@pytest.mark.parametrize("mutation", ["foreign", "missing", "omitted"])
def test_response_identity_refuses_even_with_reencoded_checkpoint_and_matching_receipt(
    field, mutation
):
    original, definition, key, record = evidence()
    response = decode_model_completion(original.completion)
    fields = (
        ("provider", "model_name", "resolved_model", "requested_model")
        if field == "combined"
        else (field,)
    )
    changed = replace(
        response,
        call_metadata=replace(
            response.call_metadata,
            **dict.fromkeys(fields, "foreign" if mutation == "foreign" else None),
        ),
    )
    encoded = encode_model_completion(changed)
    if mutation == "omitted":
        data = json.loads(encoded)
        for name in fields:
            del data["completion"]["call_metadata"][name]
        encoded = canonical_coverage_bytes(data)
    original = replace(original, completion=encoded)
    with pytest.raises(CoverageRefusedError) as failure:
        derive(original, definition, key, record)
    assert failure.value.reason == CoverageRefusalReason.UNSUPPORTED
    assert (
        validate_semantic_completion(
            definition, key, {"part-1": SOURCE}, decode_model_completion(encoded)
        ).outcome
        == "finding"
    )  # Legacy acceptance deliberately remains unchanged.


def test_actual_prepared_gateway_foreign_response_model_refused():
    original, definition, key, record = evidence(response_model="foreign-provider-model")
    response = decode_model_completion(original.completion)
    assert response.call_metadata.requested_model == "deepseek-v4-pro"
    assert (
        response.call_metadata.model_name
        == response.call_metadata.resolved_model
        == "foreign-provider-model"
    )
    with pytest.raises(CoverageRefusedError) as failure:
        derive(original, definition, key, record)
    assert failure.value.reason == CoverageRefusalReason.UNSUPPORTED
