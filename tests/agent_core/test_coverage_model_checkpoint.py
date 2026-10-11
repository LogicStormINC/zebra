"""Neutral envelopes retain exact private bytes and reject ambiguous evidence."""

import json
from dataclasses import replace

import pytest
from agent_core.domain.coverage_model_budget import CoverageModelUsageReceipt
from agent_core.domain.coverage_model_checkpoint import (
    MAX_MODEL_CHECKPOINT_BYTES,
    CoverageModelCheckpoint,
    completion_usage,
    decode_model_checkpoint,
    model_checkpoint_id,
)
from agent_core.domain.coverage_persistence import CoverageRunBinding, canonical_coverage_bytes
from agent_core.domain.identifiers import new_session_id, new_task_id

from tests.agent_core.test_coverage_contracts import contract, records, snapshot
from tests.agent_core.test_coverage_model_budget import reservation


def original_completion(*, total=10):
    return canonical_coverage_bytes(
        {
            "schema_version": 1,
            "completion": {
                "assistant_message": {
                    "role": "assistant",
                    "provider_reasoning_content": "私有\n完整",
                },
                "call_metadata": {
                    "profile_id": "review",
                    "request_hash": "b" * 64,
                    "usage": {
                        "input_tokens": 3,
                        "output_tokens": total - 3,
                        "total_tokens": total,
                    },
                },
            },
        }
    )


def checkpoint():
    items = records()
    binding = CoverageRunBinding(
        namespace="tenant-1",
        session_id=new_session_id(),
        task_id=new_task_id(),
        run_id="run-1",
        contract=contract(),
        snapshot=snapshot(items),
        manifest_artifact_digest="a" * 64,
    )
    return CoverageModelCheckpoint(binding, reservation(), original_completion())


def test_exact_opaque_bytes_and_stable_identity():
    original = checkpoint()
    changed = replace(original, completion=original.completion + b"\n")
    assert changed.artifact_id == original.artifact_id and changed.digest != original.digest
    assert decode_model_checkpoint(changed.canonical_bytes).completion == changed.completion
    assert decode_model_checkpoint(original.canonical_bytes) == original
    for field, value in (
        ("run_id", "other"),
        ("session_id", new_session_id()),
        ("task_id", new_task_id()),
    ):
        assert (
            replace(
                original, binding=original.binding.model_copy(update={field: value})
            ).artifact_id
            != original.artifact_id
        )
    for field, value in (
        ("request_digest", "c" * 64),
        ("reservation_key", "other"),
        ("model_profile", "other"),
    ):
        assert (
            model_checkpoint_id(
                original.binding, original.reservation.model_copy(update={field: value})
            )
            != original.artifact_id
        )


def test_v1_bytes_and_shape_remain_unchanged():
    original = checkpoint()
    old_bytes = canonical_coverage_bytes(
        {
            "schema": "coverage-model-checkpoint/1",
            "scope": "internal",
            "binding": original.binding.model_dump(mode="json"),
            "reservation": original.reservation.model_dump(mode="json"),
            "completion": original.completion.decode("utf-8"),
        }
    )
    assert original.request is None
    assert original.canonical_bytes == old_bytes
    restored = decode_model_checkpoint(old_bytes)
    assert restored.request is None
    assert restored.canonical_bytes == old_bytes
    assert "request" not in json.loads(old_bytes)


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"\xff",
        b"{}",
        b"{" + b'"schema_version":1,' * 2 + b'"completion":{}}',
        b'{"x":NaN}',
        b'{"x":1e999}',
        b'{"x":"\\ud800"}',
        b" " * (MAX_MODEL_CHECKPOINT_BYTES + 1),
    ],
)
def test_invalid_original_bytes(body):
    with pytest.raises(ValueError):
        completion_usage(body)


@pytest.mark.parametrize(
    "field,value",
    [
        ("input_tokens", True),
        ("output_tokens", 7.0),
        ("total_tokens", "10"),
        ("total_tokens", 11),
        ("total_tokens", None),
        ("reasoning_tokens", 8),
        ("prompt_cache_hit_tokens", 4),
        ("unknown", 1),
    ],
)
def test_usage_header_raw_types_and_equality(field, value):
    data = json.loads(original_completion())
    data["completion"]["call_metadata"]["usage"][field] = value
    with pytest.raises(ValueError):
        completion_usage(canonical_coverage_bytes(data))


@pytest.mark.parametrize(
    "field,value", [("schema", "unknown"), ("scope", "public"), ("completion", {}), ("unknown", 1)]
)
def test_unknown_envelope_scope_schema_shape(field, value):
    data = json.loads(checkpoint().canonical_bytes)
    data[field] = value
    with pytest.raises(ValueError):
        decode_model_checkpoint(canonical_coverage_bytes(data))


def test_raw_numeric_forgery_cannot_coerce_and_envelope_is_bounded(monkeypatch):
    from agent_core.domain import coverage_model_checkpoint as module

    original = checkpoint()
    data = json.loads(original.canonical_bytes)
    data["reservation"]["token_bound"] = True
    with pytest.raises(ValueError):
        decode_model_checkpoint(canonical_coverage_bytes(data))
    with pytest.raises(ValueError):
        replace(original, reservation=original.reservation.model_copy(update={"token_bound": True}))
    with pytest.raises(ValueError):
        decode_model_checkpoint(original.canonical_bytes + b"\n")
    monkeypatch.setattr(module, "MAX_MODEL_CHECKPOINT_BYTES", len(original.completion) + 10)
    with pytest.raises(ValueError, match="envelope exceeds"):
        replace(original)


def test_legacy_receipt_pair_and_exact_original_usage():
    original = checkpoint()
    legacy = CoverageModelUsageReceipt(
        reservation=original.reservation, input_tokens=3, output_tokens=4, total_tokens=10
    )
    assert legacy.checkpoint_ref is None  # Generic overhead contract remains supported.
    ref = f"artifact://{original.artifact_id}"
    with pytest.raises(ValueError, match="paired"):
        legacy.model_copy(update={"checkpoint_ref": ref}).model_validate(
            legacy.model_copy(update={"checkpoint_ref": ref})
        )
    receipt = CoverageModelUsageReceipt(
        reservation=original.reservation,
        input_tokens=3,
        output_tokens=7,
        total_tokens=10,
        checkpoint_ref=ref,
        checkpoint_digest=original.digest,
    )
    original.validate_receipt(receipt)
    with pytest.raises(ValueError):
        original.validate_receipt(legacy)
    with pytest.raises(ValueError):
        original.validate_receipt(receipt.model_copy(update={"output_tokens": 4}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("profile_id", None),
        ("profile_id", True),
        ("profile_id", "other"),
        ("request_hash", None),
        ("request_hash", "c" * 64),
        ("request_hash", 1),
    ],
)
def test_original_profile_and_request_headers_must_match_exactly(field, value):
    original = checkpoint()
    data = json.loads(original.completion)
    data["completion"]["call_metadata"][field] = value
    with pytest.raises(ValueError, match="profile/request"):
        replace(original, completion=canonical_coverage_bytes(data))
