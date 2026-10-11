"""Trusted metadata parser tests; fixtures never establish network origin."""

import json
from dataclasses import FrozenInstanceError, replace

import pytest
from agent_integrations.coverage_model_policy import (
    CHAT_URL,
    MAX_METADATA_BYTES,
    MODELS_URL,
    POLICY_VERSION,
    OfficialDeepSeekPolicy,
)


def metadata(**changes):
    return {
        "object": "list",
        "data": [
            {
                "object": "model",
                "id": "deepseek-v4-pro",
                "owned_by": "deepseek",
                "name": "DeepSeek-V4-Pro",
                "context_window": 1048576,
                "max_output_tokens": 393216,
                "input_modalities": ["text"],
                "output_modalities": ["text"],
                "effort": {"supported_levels": ["low", "high", "max"], "default_level": "high"},
                "api_capabilities": {
                    "anthropic_messages": {"system_prompt_update": "leading-only"}
                },
                **changes,
            }
        ],
    }


def proof(**changes):
    return OfficialDeepSeekPolicy(json.dumps(metadata(**changes), ensure_ascii=False).encode())


def test_original_capacity_is_full_input_and_output_and_frozen():
    policy = proof()
    assert policy.context_window == 1048576 and policy.max_output_tokens == 393216
    assert policy.effective["capacity_semantics"] == "input-plus-output"
    assert policy.effective["version"] == POLICY_VERSION
    assert policy.effective["metadata_url"] == MODELS_URL
    assert policy.effective["chat_url"] == CHAT_URL
    assert policy.original_metadata == json.dumps(metadata(), ensure_ascii=False).encode()
    with pytest.raises(FrozenInstanceError):
        policy.context_window = 1000000
    assert proof(created=1780000000).capacity_hash == policy.capacity_hash
    assert proof(context_window=1048577).capacity_hash != policy.capacity_hash
    assert proof(max_output_tokens=393217).capacity_hash != policy.capacity_hash


@pytest.mark.parametrize(
    "field,value",
    [
        ("context_window", None),
        ("context_window", True),
        ("context_window", "1048576"),
        ("context_window", 1048576.0),
        ("context_window", 0),
        ("context_window", -1),
        ("max_output_tokens", True),
        ("max_output_tokens", 8191),
        ("max_output_tokens", 1048577),
        ("max_output_tokens", None),
        ("id", "deepseek-chat"),
        ("id", "deepseek-v4-pro-alias"),
        ("owned_by", "proxy"),
        ("input_modalities", ["text", "image"]),
        ("output_modalities", ["image"]),
        ("effort", None),
        ("effort", ["high"]),
        ("effort", {"supported_levels": ["max"], "default_level": "max"}),
        ("effort", {"supported_levels": "high", "default_level": "high"}),
        ("effort", {"supported_levels": ["high", "high"], "default_level": "high"}),
        ("effort", {"supported_levels": ["high", True], "default_level": "high"}),
        ("effort", {"supported_levels": ["high"], "default_level": True}),
        ("effort", {"supported_levels": ["high"], "default_level": "low"}),
        ("effort", {"supported_levels": ["high"]}),
        ("effort", {"default_level": "high"}),
        ("effort", {"supported_levels": ["high"], "default_level": "high", "extra": 1}),
        ("object", "alias"),
        ("created", True),
        ("created", -1),
        ("created", "1770000000"),
    ],
)
def test_missing_or_unproven_raw_capability_refuses(field, value):
    with pytest.raises(ValueError):
        proof(**{field: value})


@pytest.mark.parametrize(
    "field",
    [
        "context_window",
        "max_output_tokens",
        "input_modalities",
        "output_modalities",
        "effort",
        "owned_by",
        "id",
    ],
)
def test_missing_capabilities_are_not_local_profile_defaults(field):
    data = metadata()
    del data["data"][0][field]
    with pytest.raises(ValueError):
        OfficialDeepSeekPolicy(json.dumps(data).encode())


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"\xff",
        b"[]",
        b"{}",
        b'{"object":"list","object":"list","data":[]}',
        b'{"object":"list","data":[],"created":NaN}',
        b'{"object":"list","data":[],"created":1e999}',
        b'{"object":"list","data":[],"created":"\\ud800"}',
        b" " * (MAX_METADATA_BYTES + 1),
    ],
)
def test_bounded_utf8_unique_finite_original_json(body):
    with pytest.raises(ValueError):
        OfficialDeepSeekPolicy(body)


def test_nested_duplicates_and_duplicate_model_identity_refuse():
    body = proof().original_metadata.replace(
        b'"owned_by": "deepseek"', b'"owned_by":"deepseek","owned_by":"deepseek"'
    )
    with pytest.raises(ValueError):
        OfficialDeepSeekPolicy(body)
    data = metadata()
    data["data"].append(dict(data["data"][0]))
    with pytest.raises(ValueError):
        OfficialDeepSeekPolicy(json.dumps(data).encode())


@pytest.mark.parametrize(
    "field,value",
    [
        ("metadata_url", "https://proxy.invalid/models"),
        ("metadata_url", MODELS_URL + "/"),
        ("metadata_url", MODELS_URL + "?alias=1"),
        ("chat_url", "https://proxy.invalid/chat/completions"),
        ("chat_url", CHAT_URL.replace("https:", "http:")),
        ("version", "future/2"),
    ],
)
def test_no_endpoint_alias_proxy_or_unknown_proof_version(field, value):
    with pytest.raises(ValueError):
        replace(proof(), **{field: value})


def test_exact_authenticated_provider_row_shape_is_accepted_and_preserved():
    # Exact capability row supplied by the main thread's authenticated read-only
    # GET. This parser regression still does not independently prove HTTP origin.
    original = (
        b'{"object":"list","data":[{"id":"deepseek-v4-pro","object":"model",'
        b'"owned_by":"deepseek","name":"DeepSeek-V4-Pro","context_window":1048576,'
        b'"max_output_tokens":393216,"input_modalities":["text"],"output_modalities":["text"],'
        b'"effort":{"supported_levels":["low","high","max"],"default_level":"high"},'
        b'"api_capabilities":{"anthropic_messages":{"system_prompt_update":"leading-only"}}}]}'
    )
    policy = OfficialDeepSeekPolicy(original)
    assert policy.original_metadata == original
    assert policy.context_window == 1048576 and policy.max_output_tokens == 393216
    assert policy.effective["effort"] == {
        "supported_levels": ["high", "low", "max"],
        "default_level": "high",
    }
    row = json.loads(original)["data"][0]
    assert "created" not in row and "supported_reasoning_efforts" not in row


def test_effort_alias_cannot_replace_missing_official_proof():
    data = metadata()
    del data["data"][0]["effort"]
    data["data"][0]["supported_reasoning_efforts"] = ["high"]
    with pytest.raises(ValueError):
        OfficialDeepSeekPolicy(json.dumps(data).encode())


def test_default_is_proven_member_but_request_still_pins_high():
    policy = proof(effort={"supported_levels": ["low", "high", "max"], "default_level": "low"})
    assert policy.effective["reasoning_effort"] == "high"
    assert policy.effective["effort"]["default_level"] == "low"
    assert policy.capacity_hash != proof().capacity_hash
