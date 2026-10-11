"""Neutral internal evidence envelope; provider decoding remains in integrations."""

import json
import math
from dataclasses import dataclass, fields
from hashlib import sha256
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

from agent_core.domain.coverage_contracts import coverage_digest
from agent_core.domain.coverage_model_budget import (
    CoverageModelReservation,
    CoverageModelUsageReceipt,
)
from agent_core.domain.coverage_persistence import CoverageRunBinding, canonical_coverage_bytes
from agent_core.domain.coverage_task_admission import coverage_admission_input
from agent_core.domain.identifiers import ArtifactId
from agent_core.domain.modeling import ModelCallMetadata, ModelCompletion, ModelUsage

MAX_MODEL_CHECKPOINT_BYTES = 32 * 1024 * 1024
MODEL_CHECKPOINT_KIND = "coverage-model-checkpoint-internal"


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate checkpoint JSON key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> Any:
    raise ValueError("nonfinite checkpoint JSON number")


def _tree(value: Any) -> None:
    if type(value) is str:
        value.encode("utf-8")
    elif value is None or type(value) in (bool, int):
        return
    elif type(value) is float and math.isfinite(value):
        return
    elif type(value) is list:
        for item in value:
            _tree(item)
    elif type(value) is dict:
        for key, item in value.items():
            _tree(key)
            _tree(item)
    else:
        raise ValueError("invalid/nonfinite checkpoint JSON value")


def _load(body: bytes) -> Any:
    if type(body) is not bytes or not 0 < len(body) <= MAX_MODEL_CHECKPOINT_BYTES:
        raise ValueError("checkpoint requires bounded nonempty bytes")
    try:
        result = json.loads(
            body.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_invalid_constant
        )
        _tree(result)
        return result
    except (UnicodeError, RecursionError, OverflowError) as exc:
        raise ValueError("invalid checkpoint JSON") from exc


def completion_usage(
    body: bytes, reservation: CoverageModelReservation | None = None
) -> tuple[int, int, int]:
    """Inspect only the neutral codec header, never reconstruct provider messages."""
    data = _load(body)
    if (
        type(data) is not dict
        or set(data) != {"schema_version", "completion"}
        or type(data["schema_version"]) is not int
        or data["schema_version"] != 1
    ):
        raise ValueError("unsupported original completion schema")
    completion = data["completion"]
    if (
        type(completion) is not dict
        or set(completion) - {field.name for field in fields(ModelCompletion)}
        or type(completion.get("assistant_message")) is not dict
        or completion["assistant_message"].get("role") != "assistant"
    ):
        raise ValueError("invalid original completion header")
    metadata = completion.get("call_metadata")
    if type(metadata) is not dict or set(metadata) - {
        field.name for field in fields(ModelCallMetadata)
    }:
        raise ValueError("invalid original completion metadata")
    if reservation is not None and (
        type(metadata.get("profile_id")) is not str
        or metadata["profile_id"] != reservation.model_profile
        or type(metadata.get("request_hash")) is not str
        or metadata["request_hash"] != reservation.request_digest
    ):
        raise ValueError("original completion profile/request header conflicts with reservation")
    usage = metadata.get("usage")
    if type(usage) is not dict or set(usage) - {field.name for field in fields(ModelUsage)}:
        raise ValueError("invalid original completion usage")
    for value in usage.values():
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("original usage requires exact nonnegative integers")
    counts = tuple(usage.get(name) for name in ("input_tokens", "output_tokens", "total_tokens"))
    if any(type(value) is not int for value in counts):
        raise ValueError("original completion is missing exact usage")
    input_tokens, output_tokens, total_tokens = cast(tuple[int, int, int], counts)
    if input_tokens + output_tokens != total_tokens:
        raise ValueError("original completion usage total conflicts")
    if (usage.get("reasoning_tokens") or 0) > output_tokens:
        raise ValueError("original reasoning usage exceeds completion usage")
    for name in ("prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
        if (usage.get(name) or 0) > input_tokens:
            raise ValueError("original cache usage exceeds input usage")
    return input_tokens, output_tokens, total_tokens


def model_checkpoint_id(
    binding: CoverageRunBinding, reservation: CoverageModelReservation
) -> ArtifactId:
    """Stable across fences, process replacement and response timing/content."""
    binding = CoverageRunBinding.model_validate(coverage_admission_input(binding), strict=True)
    reservation = CoverageModelReservation.model_validate(
        coverage_admission_input(reservation), strict=True
    )
    return ArtifactId(
        uuid5(
            NAMESPACE_URL,
            "coverage-model-checkpoint/1:"
            + coverage_digest(
                {
                    "binding": binding.model_dump(mode="json"),
                    "reservation": reservation.model_dump(mode="json"),
                }
            ),
        )
    )


@dataclass(frozen=True)
class CoverageModelCheckpoint:
    """V1 supports budget reads; V2 retains requests for a future derivation gate.

    A future unit gate must verify the frozen rule, exact unit and source digest
    and length; request shape/hash alone proves none of these. V2 deliberately
    shares V1's ID, so existing response-only publication must still conflict.
    """

    binding: CoverageRunBinding
    reservation: CoverageModelReservation
    completion: bytes
    request: bytes | None = None

    def __post_init__(self) -> None:
        binding = CoverageRunBinding.model_validate(
            coverage_admission_input(self.binding), strict=True
        )
        reservation = CoverageModelReservation.model_validate(
            coverage_admission_input(self.reservation), strict=True
        )
        object.__setattr__(self, "binding", binding)
        object.__setattr__(self, "reservation", reservation)
        counts = completion_usage(self.completion, reservation)
        if counts[2] > reservation.token_bound:
            raise ValueError("original usage exceeds reservation")
        if len(self.canonical_bytes) > MAX_MODEL_CHECKPOINT_BYTES:
            raise ValueError("checkpoint envelope exceeds byte limit")

    @property
    def artifact_id(self) -> ArtifactId:
        return model_checkpoint_id(self.binding, self.reservation)

    @property
    def canonical_bytes(self) -> bytes:
        data = {
            "schema": "coverage-model-checkpoint/1",
            "scope": "internal",
            "binding": self.binding.model_dump(mode="json"),
            "reservation": self.reservation.model_dump(mode="json"),
            "completion": self.completion.decode("utf-8"),
        }
        if self.request is not None:
            request = _load(self.request)
            if type(request) is not dict or not request:
                raise ValueError("original request requires a nonempty JSON object")
            if canonical_coverage_bytes(request) != self.request:
                raise ValueError("original request is not canonical")
            if sha256(self.request).hexdigest() != self.reservation.request_digest:
                raise ValueError("original request digest conflicts with reservation")
            data["schema"] = "coverage-model-checkpoint/2"
            data["request"] = self.request.decode("utf-8")
        return canonical_coverage_bytes(data)

    @property
    def digest(self) -> str:
        return sha256(self.canonical_bytes).hexdigest()

    def validate_receipt(self, receipt: CoverageModelUsageReceipt) -> None:
        receipt = CoverageModelUsageReceipt.model_validate(coverage_admission_input(receipt))
        if (
            receipt.reservation != self.reservation
            or receipt.checkpoint_ref != f"artifact://{self.artifact_id}"
            or receipt.checkpoint_digest != self.digest
            or completion_usage(self.completion, self.reservation)
            != (receipt.input_tokens, receipt.output_tokens, receipt.total_tokens)
        ):
            raise ValueError("receipt conflicts with original checkpoint")


def decode_model_checkpoint(body: bytes) -> CoverageModelCheckpoint:
    data = _load(body)
    if type(data) is not dict or data.get("schema") not in (
        "coverage-model-checkpoint/1",
        "coverage-model-checkpoint/2",
    ):
        raise ValueError("unsupported internal checkpoint envelope")
    has_request = data["schema"] == "coverage-model-checkpoint/2"
    expected = {"schema", "scope", "binding", "reservation", "completion"}
    if has_request:
        expected.add("request")
    if (
        set(data) != expected
        or data["scope"] != "internal"
        or type(data["completion"]) is not str
        or (has_request and type(data["request"]) is not str)
    ):
        raise ValueError("unsupported internal checkpoint envelope")
    # Existing CoverageTime validates ISO strings; counts/schema already reject raw
    # numeric coercion. The exact canonical round-trip below rejects normalization.
    binding = CoverageRunBinding.model_validate_json(canonical_coverage_bytes(data["binding"]))
    reservation = CoverageModelReservation.model_validate_json(
        canonical_coverage_bytes(data["reservation"])
    )
    result = CoverageModelCheckpoint(
        binding,
        reservation,
        data["completion"].encode("utf-8"),
        data["request"].encode("utf-8") if has_request else None,
    )
    if result.canonical_bytes != body:
        raise ValueError("checkpoint envelope is not canonical")
    return result
