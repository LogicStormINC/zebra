"""Exact prepared wire evidence is additive; it does not grant unit derivation."""

import json
from dataclasses import replace
from hashlib import sha256

import pytest
from agent_core.domain.coverage_model_checkpoint import (
    MAX_MODEL_CHECKPOINT_BYTES,
    decode_model_checkpoint,
)
from agent_core.domain.coverage_persistence import canonical_coverage_bytes

from tests.agent_core.test_coverage_model_checkpoint import checkpoint


def with_request(request=b'{"messages":[{"content":"source","role":"user"}]}', *, profile="review"):
    original = checkpoint()
    digest = sha256(request).hexdigest() if type(request) is bytes else "b" * 64
    reservation = original.reservation.model_copy(
        update={
            "request_digest": digest,
            "model_profile": profile,
        }
    )
    completion = json.loads(original.completion)
    completion["completion"]["call_metadata"]["request_hash"] = digest
    completion["completion"]["call_metadata"]["profile_id"] = profile
    return replace(
        original,
        reservation=reservation,
        completion=canonical_coverage_bytes(completion),
        request=request,
    )


def test_v2_exact_bytes_roundtrip_and_v1_identity():
    request = canonical_coverage_bytes({"source": '世界\n"\\', "temperature": 0.5})
    original = with_request(request)
    # The completion remains opaque, including its original whitespace.
    original = replace(original, completion=original.completion + b"\n  ")
    legacy = replace(original, request=None)
    restored = decode_model_checkpoint(original.canonical_bytes)
    assert restored == original
    assert restored.request == request
    assert restored.completion == original.completion
    assert restored.canonical_bytes == original.canonical_bytes
    data = json.loads(original.canonical_bytes)
    assert data["schema"] == "coverage-model-checkpoint/2"
    assert data["request"].encode("utf-8") == request
    assert original.artifact_id == legacy.artifact_id
    assert original.digest != legacy.digest  # Same-ID publication must still conflict.
    changed = replace(original, completion=original.completion + b"\n")
    assert changed.artifact_id == original.artifact_id
    assert changed.digest != original.digest


def test_wrong_request_digest_refuses():
    original = with_request()
    with pytest.raises(ValueError, match="request digest"):
        replace(original, request=b'{"other":1}')


@pytest.mark.parametrize(
    "wire",
    [
        b"",
        "{}",
        bytearray(b'{"x":1}'),
        memoryview(b'{"x":1}'),
        1,
        True,
        b"\xff",
        b'{"x":"\xed\xa0\x80"}',
        b'{"x":"\\ud800"}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b'{"x":1e999}',
        b'{"x":1,"x":2}',
        b'{"x":{"a":1,"a":2}}',
        b'{"x":',
        b"{}",
        b"[]",
        b"null",
        b"1",
        b'"source"',
        b' {"x":1}',
        b'{"x":1}\n',
        b'{"x": 1}',
        b'{"z":1,"a":2}',
        b'{"x":"\\u4e16"}',
        b'{"x":1.00}',
        b'{"x":-0}',
        b'\xef\xbb\xbf{"x":1}',
        b'{"x":1}\x00',
    ],
)
def test_invalid_original_request_refuses_before_normalization(wire):
    with pytest.raises(ValueError):
        with_request(wire)


def test_bytes_subclass_is_not_raw_wire():
    class Wire(bytes):
        pass

    with pytest.raises(ValueError):
        with_request(Wire(b'{"x":1}'))


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema", "coverage-model-checkpoint/3"),
        ("schema", None),
        ("schema", []),
        ("request", None),
        ("request", {}),
        ("request", []),
        ("request", 1),
        ("request", ""),
        ("request", "{}"),
        ("request", '{"x":NaN}'),
        ("request", '{"x":1,"x":2}'),
        ("request", '{"x":"\\ud800"}'),
        ("request", ' {"x":1}'),
        ("unknown", 1),
        ("scope", "public"),
    ],
)
def test_v2_envelope_rejects_unknown_or_invalid_fields(field, value):
    data = json.loads(with_request().canonical_bytes)
    data[field] = value
    with pytest.raises(ValueError):
        decode_model_checkpoint(canonical_coverage_bytes(data))


def test_v2_requires_request_and_v1_refuses_request_extra():
    data = json.loads(with_request().canonical_bytes)
    data["schema"] = "coverage-model-checkpoint/1"
    with pytest.raises(ValueError):
        decode_model_checkpoint(canonical_coverage_bytes(data))
    data["schema"] = "coverage-model-checkpoint/2"
    del data["request"]
    with pytest.raises(ValueError):
        decode_model_checkpoint(canonical_coverage_bytes(data))


def test_v2_parser_rejects_digest_mismatch_and_ambiguous_envelope():
    original = with_request()
    data = json.loads(original.canonical_bytes)
    data["request"] = '{"other":1}'
    with pytest.raises(ValueError, match="request digest"):
        decode_model_checkpoint(canonical_coverage_bytes(data))
    duplicate = original.canonical_bytes[:-1] + b',"request":"{}"}'
    with pytest.raises(ValueError, match="duplicate"):
        decode_model_checkpoint(duplicate)
    with pytest.raises(ValueError, match="not canonical"):
        decode_model_checkpoint(original.canonical_bytes + b"\n")


@pytest.mark.parametrize("value", [True, 10.0, "10", None])
def test_v2_completion_usage_counts_remain_strict(value):
    original = with_request()
    completion = json.loads(original.completion)
    completion["completion"]["call_metadata"]["usage"]["total_tokens"] = value
    with pytest.raises(ValueError):
        replace(original, completion=canonical_coverage_bytes(completion))


def test_original_request_itself_must_fit_byte_limit(monkeypatch):
    from agent_core.domain import coverage_model_checkpoint as module

    original = with_request()
    monkeypatch.setattr(module, "MAX_MODEL_CHECKPOINT_BYTES", len(original.completion))
    with pytest.raises(ValueError, match="bounded"):
        replace(original, request=b'{"source":"' + b"x" * len(original.completion) + b'"}')


@pytest.mark.parametrize("value", [True, False, 100.0, "100", None])
def test_v2_reservation_counts_remain_strict(value):
    data = json.loads(with_request().canonical_bytes)
    data["reservation"]["token_bound"] = value
    with pytest.raises(ValueError):
        decode_model_checkpoint(canonical_coverage_bytes(data))


@pytest.mark.parametrize("field", ["binding", "reservation"])
def test_v2_forged_typed_unknown_attributes_refuse(field):
    original = with_request()
    forged = getattr(original, field).model_copy(update={"unknown": 1})
    with pytest.raises(ValueError, match="unknown attributes"):
        replace(original, **{field: forged})


def test_combined_envelope_ceiling_counts_escaping_and_never_truncates(monkeypatch):
    from agent_core.domain import coverage_model_checkpoint as module

    assert MAX_MODEL_CHECKPOINT_BYTES == 32 * 1024 * 1024
    original = with_request(canonical_coverage_bytes({"source": '世界"\\' * 100}))
    body = original.canonical_bytes
    assert len(original.request) < len(body)
    assert len(original.completion) < len(body)
    monkeypatch.setattr(module, "MAX_MODEL_CHECKPOINT_BYTES", len(body))
    assert decode_model_checkpoint(body).canonical_bytes == body
    monkeypatch.setattr(module, "MAX_MODEL_CHECKPOINT_BYTES", len(body) - 1)
    with pytest.raises(ValueError, match="envelope exceeds"):
        replace(original)
    with pytest.raises(ValueError, match="bounded"):
        decode_model_checkpoint(body)
    assert original.request == canonical_coverage_bytes({"source": '世界"\\' * 100})
    assert original.canonical_bytes == body


def test_actual_prepared_gateway_body_matches_core_canonical_representation():
    from datetime import UTC, datetime

    from agent_core.domain.identifiers import new_message_id
    from agent_core.domain.messages import MessageRole, SessionMessage
    from agent_core.domain.modeling import ModelInvocationPolicy, ModelRole, ModelToolChoice
    from agent_integrations.openai_compatible import OpenAICompatibleModelGateway
    from agent_integrations.request_metadata import _canonical_json

    gateway = OpenAICompatibleModelGateway(
        provider_name="deepseek",
        base_url="https://model.example/v1",
        api_key="fixture",
        model_name="legacy",
        max_retries=0,
    )
    prepared = gateway.prepare_text_request(
        [
            SessionMessage(
                message_id=new_message_id(),
                created_at=datetime.now(UTC),
                role=MessageRole.USER,
                content='source 世界\n"\\',
            )
        ],
        invocation_policy=ModelInvocationPolicy(
            role=ModelRole.REVIEWER,
            tool_choice=ModelToolChoice.NONE,
            max_output_tokens=8192,
            profile_id="deepseek-v4-pro-reviewer-v1",
        ),
    )
    assert prepared.body == _canonical_json(json.loads(prepared.body))
    assert prepared.body == canonical_coverage_bytes(json.loads(prepared.body))
    original = with_request(prepared.body, profile=prepared.resolved.profile.profile_id)
    assert original.reservation.request_digest == prepared.request_digest
    assert decode_model_checkpoint(original.canonical_bytes).request == prepared.body
