"""Full checkpoint preservation and hostile raw-input checks; no provider calls."""

import json
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID
from zoneinfo import TZPATH, ZoneInfo

import pytest
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    CONTEXT_TOKEN_CATEGORIES,
    ModelCallMetadata,
    ModelCompletion,
    ModelTokenBreakdown,
    ModelUsage,
)
from agent_core.domain.tools import ToolCall
from agent_integrations.coverage_model_completion import (
    MAX_MODEL_COMPLETION_BYTES,
    decode_model_completion,
    encode_model_completion,
)
from agent_integrations.openai_payloads import parse_completion


def completion():
    tool = ToolCall(
        tool_call_id=new_tool_call_id(),
        name="read",
        arguments={"路径": [True, None, 1.5]},
        created_at=datetime.now(UTC),
        provider_call_id="provider-call",
        provider_tool_name="wire_read",
        provider_arguments={"file": "资料"},
    )
    return ModelCompletion(
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content="答复 🦓",
            created_at=datetime.now(UTC),
            tool_calls=(tool,),
            metadata={"nested": {"values": [False, None, 3, 2.5, "中文"]}},
            provider_reasoning_content="私有推理\n完整保留",
        ),
        (tool,),
        ModelCallMetadata(
            **{
                field.name: "value"
                for field in fields(ModelCallMetadata)
                if field.type == str | None
            },
            latency_ms=0,
            cache_hit=False,
            cost_usd=0.125,
            estimated_input_tokens=12,
            input_token_limit=100,
            token_breakdown={"messages": 12},
            token_breakdown_v2=ModelTokenBreakdown(
                dict.fromkeys(CONTEXT_TOKEN_CATEGORIES, 2),
                "basis",
                "method",
                15,
                12,
                -3,
            ),
            tool_schema_bytes=12,
            message_count=2,
            message_prefix_hashes=("a", "b"),
            time_to_first_event_ms=1,
            time_to_first_public_text_ms=2,
            retry_count=1,
            response_repair_count=2,
            usage=ModelUsage(12, 7, 19, 3, 2, 10),
        ),
    )


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def checkpoint(body):
    return canonical({"schema_version": 1, "completion": body})


def test_full_roundtrip_preserves_every_field_and_private_reasoning():
    original = completion()
    encoded = encode_model_completion(original)
    restored = decode_model_completion(encoded)
    assert restored == original
    assert restored.assistant_message.provider_reasoning_content == "私有推理\n完整保留"
    assert restored.assistant_message.provider_image_data_urls == ()
    assert encode_model_completion(restored) == encoded
    assert "答复 🦓".encode() in encoded
    assert b"provider_image_data_urls" in encoded
    assert b"provider_reasoning_content" in encoded
    assert type(restored.call_metadata.usage) is ModelUsage
    assert type(restored.call_metadata.token_breakdown_v2) is ModelTokenBreakdown
    assert type(restored.tool_calls[0]) is ToolCall


def test_parser_produced_completion_roundtrips_without_provider():
    original = parse_completion(
        {
            "id": "call-1",
            "model": "model",
            "system_fingerprint": "fingerprint",
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": "hidden",
                        "tool_calls": [
                            {
                                "id": "tc",
                                "type": "function",
                                "function": {"name": "read", "arguments": '{"file":"中文"}'},
                            }
                        ],
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "completion_tokens_details": {"reasoning_tokens": 2},
                "prompt_cache_hit_tokens": 4,
                "prompt_cache_miss_tokens": 6,
            },
        },
        provider_name="deepseek",
        default_model_name="model",
        latency_ms=12,
    )
    assert decode_model_completion(encode_model_completion(original)) == original


def test_omitted_defaults_decode_to_same_canonical_bytes():
    original = ModelCompletion(
        SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content="ok",
            created_at=datetime.now(UTC),
        )
    )
    encoded = encode_model_completion(original)
    body = json.loads(encoded)["completion"]
    del body["tool_calls"]
    del body["call_metadata"]
    for key in (
        "metadata",
        "tool_calls",
        "tool_call_id",
        "provider_reasoning_content",
        "provider_image_data_urls",
    ):
        del body["assistant_message"][key]
    assert encode_model_completion(decode_model_completion(checkpoint(body))) == encoded


@pytest.mark.parametrize("model", [ModelCallMetadata, ModelUsage, ModelTokenBreakdown])
@pytest.mark.parametrize("bad", [True, 1.0, "1"])
def test_every_counter_rejects_coercion_on_encode_and_decode(model, bad):
    original = completion()
    instance = {
        ModelCallMetadata: original.call_metadata,
        ModelUsage: original.call_metadata.usage,
        ModelTokenBreakdown: original.call_metadata.token_breakdown_v2,
    }[model]
    for field in fields(model):
        if field.type not in (int, int | None):
            continue
        # Bypass frozen constructors just as hostile runtime mutation can.
        altered = replace(instance)
        object.__setattr__(altered, field.name, bad)
        metadata = (
            altered
            if model is ModelCallMetadata
            else replace(
                original.call_metadata,
                **{"usage" if model is ModelUsage else "token_breakdown_v2": altered},
            )
        )
        with pytest.raises(ValueError):
            encode_model_completion(replace(original, call_metadata=metadata))
        body = json.loads(encode_model_completion(original))["completion"]
        target = body["call_metadata"]
        if model is not ModelCallMetadata:
            target = target["usage" if model is ModelUsage else "token_breakdown_v2"]
        target[field.name] = bad
        with pytest.raises(ValueError):
            decode_model_completion(checkpoint(body))


@pytest.mark.parametrize(
    "target", ["completion", "message", "tool", "metadata", "usage", "breakdown"]
)
def test_unknown_fields_rejected_before_serialization_or_normalization(target):
    original = completion()
    instance = {
        "completion": original,
        "message": original.assistant_message,
        "tool": original.tool_calls[0],
        "metadata": original.call_metadata,
        "usage": original.call_metadata.usage,
        "breakdown": original.call_metadata.token_breakdown_v2,
    }[target]
    object.__setattr__(instance, "illicit", 1)
    with pytest.raises(ValueError):
        encode_model_completion(original)
    body = json.loads(encode_model_completion(completion()))["completion"]
    nested = {
        "completion": body,
        "message": body["assistant_message"],
        "tool": body["tool_calls"][0],
        "metadata": body["call_metadata"],
        "usage": body["call_metadata"]["usage"],
        "breakdown": body["call_metadata"]["token_breakdown_v2"],
    }[target]
    nested["illicit"] = 1
    with pytest.raises(ValueError):
        decode_model_completion(checkpoint(body))


@pytest.mark.parametrize(
    "field,bad",
    [
        ("content", 3),
        ("content", " ok "),
        ("role", "assistant"),
        ("tool_calls", []),
        ("metadata", {"bad": (1, 2)}),
        ("metadata", {1: "bad"}),
        ("metadata", {"bad": float("nan")}),
        ("metadata", {"bad": object()}),
        ("provider_reasoning_content", 7),
        ("provider_image_data_urls", ["data:image/png;base64,AA"]),
        ("provider_image_data_urls", ("data:image/png;base64,AA",)),
        ("created_at", datetime(2026, 1, 1)),
        ("unknown", "bad"),
        ("created_at", "2026-01-01T00:00:00+00:00"),
        ("message_id", "not-a-uuid"),
    ],
)
def test_model_copy_illicit_shapes_are_rejected(field, bad):
    original = completion()
    message = original.assistant_message.model_copy(update={field: bad})
    object.__setattr__(original, "assistant_message", message)
    with pytest.raises(ValueError):
        encode_model_completion(original)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("tool_call_id", "123"),
        ("name", " read "),
        ("name", True),
        ("created_at", "2026-01-01T00:00:00+00:00"),
        ("created_at", datetime(2026, 1, 1)),
        ("provider_call_id", " call "),
        ("provider_tool_name", " wire "),
        ("provider_arguments", None),
        ("arguments", {"x": (1,)}),
        ("arguments", {"x": float("inf")}),
        ("unknown", "value"),
    ],
)
def test_mutated_tool_fields_rejected_in_both_tool_locations(field, bad):
    for location in ("completion", "message"):
        original = completion()
        bad_tool = original.tool_calls[0].model_copy(update={field: bad})
        if location == "completion":
            object.__setattr__(original, "tool_calls", (bad_tool,))
        else:
            object.__setattr__(
                original,
                "assistant_message",
                original.assistant_message.model_copy(
                    update={"tool_calls": (bad_tool,)},
                ),
            )
        with pytest.raises(ValueError):
            encode_model_completion(original)


@pytest.mark.parametrize("bad", [True, 1.0, "1", -1])
def test_breakdown_mapping_counters_rejected_on_both_boundaries(bad):
    for field in ("token_breakdown", "token_breakdown_v2"):
        original = completion()
        body = json.loads(encode_model_completion(original))["completion"]
        if field == "token_breakdown":
            original.call_metadata.token_breakdown["messages"] = bad
            body["call_metadata"][field]["messages"] = bad
        else:
            original.call_metadata.token_breakdown_v2.categories["messages"] = bad
            body["call_metadata"][field]["categories"]["messages"] = bad
        with pytest.raises(ValueError):
            encode_model_completion(original)
        with pytest.raises(ValueError):
            decode_model_completion(checkpoint(body))


@pytest.mark.parametrize(
    "field,bad",
    [
        ("cache_hit", 1),
        ("cost_usd", True),
        ("cost_usd", float("nan")),
        ("cost_usd", float("inf")),
        ("cost_usd", -1),
        ("provider", " "),
        ("message_prefix_hashes", ["a"]),
        ("usage", {"input_tokens": 1}),
        ("token_breakdown_v2", {"categories": {}}),
    ],
)
def test_frozen_metadata_mutation_is_checked_before_normalization(field, bad):
    original = completion()
    object.__setattr__(original.call_metadata, field, bad)
    with pytest.raises(ValueError):
        encode_model_completion(original)


def test_mapping_order_and_integral_cost_do_not_change_supported_values():
    original = completion()
    object.__setattr__(original.call_metadata, "cost_usd", 0)
    encoded = encode_model_completion(original)
    original.assistant_message.metadata["nested"]["values"] = [False, None, 3, 2.5, "中文"]
    reordered = json.loads(encoded)
    reordered = dict(reversed(list(reordered.items())))
    restored = decode_model_completion(json.dumps(reordered).encode())
    assert encode_model_completion(restored) == encoded
    assert decode_model_completion(encoded) == original


def test_cycles_and_excessive_depth_fail_closed():
    original = completion()
    original.assistant_message.metadata["cycle"] = original.assistant_message.metadata
    with pytest.raises(ValueError):
        encode_model_completion(original)
    with pytest.raises(ValueError):
        decode_model_completion(b"[" * 2000 + b"0" + b"]" * 2000)


def test_valid_looking_raw_id_strings_cannot_replace_typed_ids():
    original = completion()
    object.__setattr__(
        original.assistant_message, "message_id", str(original.assistant_message.message_id)
    )
    with pytest.raises(ValueError):
        encode_model_completion(original)


@pytest.mark.parametrize(
    "zone,fold",
    [
        (timezone(timedelta(hours=5, minutes=30)), 0),
        (ZoneInfo("America/New_York"), 0),
        (ZoneInfo("America/New_York"), 1),
    ],
)
def test_timestamps_preserve_equality_including_ambiguous_zoneinfo_hours(zone, fold):
    original = completion()
    timestamp = datetime(2026, 11, 1, 1, 30, 12, 123456, tzinfo=zone, fold=fold)
    object.__setattr__(original.assistant_message, "created_at", timestamp)
    object.__setattr__(original.tool_calls[0], "created_at", timestamp)
    restored = decode_model_completion(encode_model_completion(original))
    assert restored == original
    assert restored.assistant_message.created_at == timestamp
    assert restored.tool_calls[0].created_at == timestamp
    if type(zone) is ZoneInfo:
        assert restored.assistant_message.created_at.fold == fold


@pytest.mark.parametrize("offset_us", [1, -1, 999999, -999999, 1000001, -1000001])
def test_fractional_fixed_offsets_preserve_complete_response(offset_us):
    original = completion()
    timestamp = datetime(
        2026, 11, 1, 1, 30, 12, 345678, tzinfo=timezone(timedelta(microseconds=offset_us))
    )
    object.__setattr__(original.assistant_message, "created_at", timestamp)
    object.__setattr__(original.tool_calls[0], "created_at", timestamp)
    encoded = encode_model_completion(original)
    wire_timestamp = json.loads(encoded)["completion"]["assistant_message"]["created_at"]
    assert type(wire_timestamp["offset_us"]) is int
    assert wire_timestamp["offset_us"] == offset_us
    restored = decode_model_completion(encoded)
    assert restored == original
    assert restored.assistant_message.created_at.utcoffset() == timestamp.utcoffset()
    assert restored.tool_calls[0].created_at.utcoffset() == timestamp.utcoffset()
    assert encode_model_completion(restored) == encoded


def test_legacy_string_cannot_silently_discard_fractional_offset():
    body = json.loads(encode_model_completion(completion()))["completion"]
    body["assistant_message"]["created_at"] = "2026-01-01T00:00:00+00:00:00.000001"
    with pytest.raises(ValueError):
        decode_model_completion(checkpoint(body))


@pytest.mark.parametrize(
    "update",
    [
        {"offset_us": True},
        {"offset_us": 1.0},
        {"offset_us": "1"},
        {"offset_us": 86400000000},
        {"offset_us": -86400000000},
        {"offset_us": -1},
        {"iso": "2026-01-01T00:00:00"},
        {"fold": True},
        {"extra": 1},
    ],
)
def test_fixed_offset_wire_validates_exact_shape_and_offset(update):
    body = json.loads(encode_model_completion(completion()))["completion"]
    body["assistant_message"]["created_at"] = {
        "iso": "2026-01-01T00:00:00+00:00:00.000001",
        "offset_us": 1,
        "fold": 0,
        **update,
    }
    with pytest.raises(ValueError):
        decode_model_completion(checkpoint(body))


@pytest.mark.parametrize("bad", ["\ud800", "\udfff", "secret\ud800reasoning"])
@pytest.mark.parametrize(
    "location",
    [
        "content",
        "reasoning",
        "metadata_value",
        "metadata_key",
        "argument_value",
        "argument_key",
        "provider_argument_key",
        "provider",
        "breakdown_key",
    ],
)
def test_surrogates_rejected_on_encode_and_raw_decode_with_generic_error(bad, location):
    original = completion()
    body = json.loads(encode_model_completion(original))["completion"]
    message, raw_message = original.assistant_message, body["assistant_message"]
    tool, raw_tool = original.tool_calls[0], body["tool_calls"][0]
    if location in ("content", "reasoning"):
        field = "content" if location == "content" else "provider_reasoning_content"
        object.__setattr__(message, field, bad)
        raw_message[field] = bad
    else:
        mappings = {
            "metadata_value": (message.metadata, raw_message["metadata"], "value", bad),
            "metadata_key": (message.metadata, raw_message["metadata"], bad, "value"),
            "argument_value": (tool.arguments, raw_tool["arguments"], "value", bad),
            "argument_key": (tool.arguments, raw_tool["arguments"], bad, "value"),
            "provider_argument_key": (
                tool.provider_arguments,
                raw_tool["provider_arguments"],
                bad,
                "value",
            ),
            "breakdown_key": (
                original.call_metadata.token_breakdown,
                body["call_metadata"]["token_breakdown"],
                bad,
                1,
            ),
        }
        if location == "provider":
            object.__setattr__(original.call_metadata, "provider", bad)
            body["call_metadata"]["provider"] = bad
        else:
            runtime, raw, key, value = mappings[location]
            runtime[key] = raw[key] = value
    for operation in (
        lambda: encode_model_completion(original),
        lambda: decode_model_completion(
            json.dumps({"schema_version": 1, "completion": body}, ensure_ascii=True).encode(),
        ),
    ):
        with pytest.raises(ValueError) as error:
            operation()
        assert bad not in str(error.value)
        assert "secret" not in str(error.value)
        assert not isinstance(error.value, UnicodeEncodeError)


@pytest.mark.parametrize("fold", [0, 1])
@pytest.mark.parametrize("kind", ["no_cache", "from_file", "from_file_without_key"])
def test_noncanonical_zones_fail_before_encoding_in_both_timestamp_locations(kind, fold):
    if kind == "no_cache":
        zone = ZoneInfo.no_cache("America/New_York")
    else:
        path = next(
            (
                Path(root) / "America/New_York"
                for root in TZPATH
                if (Path(root) / "America/New_York").is_file()
            ),
            None,
        )
        if path is None:
            pytest.skip("system zoneinfo file unavailable")
        with path.open("rb") as stream:
            zone = ZoneInfo.from_file(
                stream, key="America/New_York" if kind == "from_file" else None
            )
    timestamp = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=fold)
    for location in ("message", "tool"):
        original = completion()
        target = original.assistant_message if location == "message" else original.tool_calls[0]
        object.__setattr__(target, "created_at", timestamp)
        with pytest.raises(ValueError):
            encode_model_completion(original)


@pytest.mark.parametrize("bad", [True, 1.0, -1, 1 << 128])
def test_uuid_internal_int_mutations_fail_before_encoding_in_both_id_locations(bad):
    for location in ("message", "tool"):
        original = completion()
        identifier = (
            original.assistant_message.message_id
            if location == "message"
            else original.tool_calls[0].tool_call_id
        )
        object.__setattr__(identifier, "int", bad)
        with pytest.raises(ValueError):
            encode_model_completion(original)


def test_uuid_extra_attributes_are_impossible_or_refused_for_custom_shapes():
    original = completion()
    with pytest.raises(AttributeError):
        object.__setattr__(original.assistant_message.message_id, "extra", "illicit")
    assert decode_model_completion(encode_model_completion(original)) == original

    class CustomUUID(UUID):
        pass

    identifier = CustomUUID(int=original.assistant_message.message_id.int)
    object.__setattr__(identifier, "extra", "illicit")
    object.__setattr__(original.assistant_message, "message_id", identifier)
    with pytest.raises(ValueError):
        encode_model_completion(original)


@pytest.mark.parametrize("bad", ["forged", "user", True, 1.0])
def test_enum_internal_value_mutation_rejected_and_global_member_restored(bad):
    original = completion()
    member = MessageRole.ASSISTANT
    previous = member._value_
    try:
        object.__setattr__(member, "_value_", bad)
        with pytest.raises(ValueError):
            encode_model_completion(original)
    finally:
        object.__setattr__(member, "_value_", previous)
    assert decode_model_completion(encode_model_completion(original)) == original


@pytest.mark.parametrize(
    "update",
    [
        {"fold": True},
        {"fold": 2},
        {"zone": "nonexistent/zone"},
        {"iso": "2026-11-01T01:30:00+00:00"},
        {"extra": 1},
    ],
)
def test_raw_zoned_timestamp_shape_and_offset_are_validated(update):
    body = json.loads(encode_model_completion(completion()))["completion"]
    body["assistant_message"]["created_at"] = {
        "iso": "2026-11-01T01:30:00-04:00",
        "zone": "America/New_York",
        "fold": 0,
        **update,
    }
    with pytest.raises(ValueError):
        decode_model_completion(checkpoint(body))


@pytest.mark.parametrize(
    "bad",
    [
        b"",
        b"{}",
        b"null",
        b"\xff",
        b'{"schema_version":1,',
        b'{"schema_version":1,"schema_version":1}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":1e999}',
    ],
)
def test_malformed_json_is_rejected(bad):
    with pytest.raises(ValueError):
        decode_model_completion(bad)


@pytest.mark.parametrize(
    "change",
    ["schema", "bool_schema", "extra", "content", "missing", "nested_duplicate", "counter"],
)
def test_tampered_envelope_or_payload_is_rejected(change):
    envelope = json.loads(encode_model_completion(completion()))
    if change == "schema":
        envelope["schema_version"] = 2
    elif change == "bool_schema":
        envelope["schema_version"] = True
    elif change == "extra":
        envelope["extra"] = 1
    elif change == "content":
        envelope["completion"]["assistant_message"]["content"] = " changed "
    elif change == "missing":
        del envelope["completion"]["assistant_message"]["message_id"]
    elif change == "counter":
        envelope["completion"]["call_metadata"]["usage"]["total_tokens"] = True
    encoded = canonical(envelope)
    if change == "nested_duplicate":
        encoded = encoded.replace(b'"retry_count":1', b'"retry_count":1,"retry_count":1')
    with pytest.raises(ValueError):
        decode_model_completion(encoded)


def test_explicit_byte_limit_rejects_without_truncating_and_accepts_boundary():
    assert 0 < MAX_MODEL_COMPLETION_BYTES <= 32 * 1024 * 1024
    original = completion()
    baseline = encode_model_completion(original)
    content = "x" * (MAX_MODEL_COMPLETION_BYTES - len(baseline) + len("答复 🦓".encode()))
    exact = replace(
        original,
        assistant_message=original.assistant_message.model_copy(
            update={"content": content},
        ),
    )
    encoded = encode_model_completion(exact)
    assert len(encoded) == MAX_MODEL_COMPLETION_BYTES
    assert decode_model_completion(encoded) == exact
    with pytest.raises(ValueError):
        decode_model_completion(encoded + b" ")
    with pytest.raises(ValueError):
        encode_model_completion(
            replace(
                exact,
                assistant_message=exact.assistant_message.model_copy(
                    update={"content": content + "x"},
                ),
            )
        )
