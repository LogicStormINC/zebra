"""Derive annotations from original private Artifact bytes and a settled receipt.

The caller proves private Artifact provenance, receipt settlement, immutable
manifest binding/membership and current lifecycle/Event authority. A supplied
CoverageRecord alone does not prove full manifest membership. This pure validator
proves request/source/response derivation, not authority, materialized Events, a
coverage certificate or external truth of the source/model's semantic claims.
"""

import json

from agent_core.application.coverage_semantic import semantic_check
from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_core.domain.coverage_execution import CoverageObservation, PublishedCoverageCheck
from agent_core.domain.coverage_model_budget import CoverageModelUsageReceipt
from agent_core.domain.coverage_model_checkpoint import decode_model_checkpoint
from agent_core.domain.coverage_persistence import CoverageRunBinding, canonical_coverage_bytes
from agent_core.domain.coverage_snapshot import CoverageRecord
from agent_core.domain.coverage_task_admission import coverage_admission_input
from agent_core.domain.coverage_validation import CoverageUnitKey
from agent_core.domain.modeling import (
    ModelCompletion,
    ModelReasoningEffort,
    ModelRole,
    ModelThinkingMode,
    ModelToolChoice,
)

from agent_integrations.coverage_model import validate_semantic_completion
from agent_integrations.coverage_model_completion import decode_model_completion
from agent_integrations.coverage_snapshot_invocation import unique_object
from agent_integrations.deepseek_profiles import deepseek_profile


def derive_semantic_observation(
    checkpoint_bytes: bytes,
    receipt: CoverageModelUsageReceipt,
    definition: PublishedCoverageCheck,
    key: CoverageUnitKey,
    record: CoverageRecord,
) -> CoverageObservation:
    """Require bounded_semantic/1's exact configured reviewer wire and manifest part.

    No provider calls, retries, repairs, persistence or authority checks occur here.
    Response-only v1 remains budget evidence and cannot pass this derivation gate.
    """
    try:
        checkpoint = decode_model_checkpoint(checkpoint_bytes)
        checkpoint.validate_receipt(receipt)
        if (
            checkpoint.request is None
            or checkpoint.reservation.key != key
            or checkpoint.reservation.model_profile != definition.model_profile
        ):
            raise ValueError("checkpoint does not bind the admitted semantic part")
        bodies = validate_semantic_request(
            checkpoint.binding, checkpoint.request, definition, key, record
        )
        response = decode_model_completion(checkpoint.completion)
        validate_semantic_response_identity(definition, response)
    except CoverageRefusedError:
        raise
    except (ValueError, TypeError, RecursionError, OverflowError) as error:
        raise CoverageRefusedError(CoverageRefusalReason.UNSUPPORTED) from error
    return validate_semantic_completion(definition, key, bodies, response)


def validate_semantic_request(
    binding: CoverageRunBinding,
    request_bytes: bytes,
    definition: PublishedCoverageCheck,
    key: CoverageUnitKey,
    record: CoverageRecord,
) -> dict[str, str]:
    """Shared exact frozen rule/unit/source gate, including before reservation.

    Membership and current lifecycle remain the caller's responsibility.
    """
    try:
        definition = PublishedCoverageCheck.model_validate(
            coverage_admission_input(definition), strict=True
        )
        key = CoverageUnitKey.model_validate(coverage_admission_input(key), strict=True)
        record = CoverageRecord.model_validate(coverage_admission_input(record), strict=True)
        if definition.model_profile is None or definition != semantic_check(
            definition.model_profile
        ):
            raise ValueError("unsupported frozen semantic definition")
        profile = deepseek_profile(definition.model_profile)
        if (
            ModelRole.REVIEWER not in profile.roles
            or profile.thinking_mode is not ModelThinkingMode.ENABLED
            or profile.reasoning_effort is not ModelReasoningEffort.HIGH
        ):
            raise ValueError("unsupported semantic reviewer profile")
        if key.kind != "part" or (key.record_id, key.content_digest) != record.identity:
            raise ValueError("checkpoint does not bind the admitted semantic part")
        part = next((part for part in record.parts if part.id == key.part_id), None)
        check = definition.contract_check
        if (
            part is None
            or part.digest != key.part_digest
            or check not in binding.contract.checks
            or (key.check_id, key.check_version, key.definition_digest)
            != (check.id, check.version, check.definition_digest)
        ):
            raise ValueError("semantic unit does not match manifest or frozen check")
        if type(request_bytes) is not bytes or not 0 < len(request_bytes) <= 32 * 1024 * 1024:
            raise ValueError("unsupported semantic request size")
        request = json.loads(request_bytes.decode("utf-8"), object_pairs_hook=unique_object)
        if type(request) is not dict or canonical_coverage_bytes(request) != request_bytes:
            raise ValueError("unsupported semantic request representation")
        if (
            set(request)
            != {"model", "messages", "stream", "thinking", "max_tokens", "reasoning_effort"}
            or request["model"] != profile.model
            or type(request["stream"]) is not bool
            or request["stream"] is not False
            or request["thinking"] != {"type": profile.thinking_mode.value}
            or type(request["max_tokens"]) is not int
            or request["max_tokens"] != 8192
            or request["reasoning_effort"] != profile.reasoning_effort.value
        ):
            raise ValueError("unsupported semantic request wire")
        messages = request["messages"]
        if type(messages) is not list or len(messages) != 2:
            raise ValueError("semantic request requires exactly system/user messages")
        for message, role in zip(messages, ("system", "user"), strict=True):
            if (
                type(message) is not dict
                or set(message) != {"role", "content"}
                or message["role"] != role
                or type(message["content"]) is not str
            ):
                raise ValueError("unsupported semantic message wire")
        if messages[0]["content"] != definition.instructions:
            raise ValueError("semantic request changed frozen instructions")
        payload = json.loads(messages[1]["content"], object_pairs_hook=unique_object)
        # Encoding checks every embedded string/number before any typed normalization.
        canonical_coverage_bytes(payload)
        if (
            type(payload) is not dict
            or set(payload) != {"key", "bodies"}
            or canonical_coverage_bytes(payload["key"])
            != canonical_coverage_bytes(key.model_dump(mode="json"))
            or type(payload["bodies"]) is not dict
            or set(payload["bodies"]) != {part.id}
            or type(payload["bodies"][part.id]) is not str
            or len(payload["bodies"][part.id]) > definition.max_part_characters
        ):
            raise ValueError("semantic request changed exact unit or source shape")
        bodies = payload["bodies"]
        part.verify_bytes(bodies[part.id].encode("utf-8"))
        return bodies
    except CoverageRefusedError:
        raise
    except (ValueError, TypeError, RecursionError, OverflowError) as error:
        raise CoverageRefusedError(CoverageRefusalReason.UNSUPPORTED) from error


def validate_semantic_response_identity(
    definition: PublishedCoverageCheck, response: ModelCompletion
) -> None:
    """Reject foreign identity before acknowledging usage; semantics follow accounting."""
    try:
        if definition.model_profile is None:
            raise ValueError("missing configured semantic profile")
        profile = deepseek_profile(definition.model_profile)
        if profile.reasoning_effort is not ModelReasoningEffort.HIGH:
            raise ValueError("unsupported semantic response profile")
        expected_metadata = {
            "provider": "deepseek",
            "requested_model": profile.model,
            "resolved_model": profile.model,
            "model_name": profile.model,
            "role": ModelRole.REVIEWER.value,
            "thinking_mode": profile.thinking_mode.value,
            "reasoning_effort": profile.reasoning_effort.value,
            "tool_choice": ModelToolChoice.NONE.value,
            "prompt_version": profile.prompt_version,
            "profile_version_observed_at": profile.version_observed_at,
        }
        if any(
            getattr(response.call_metadata, field) != expected
            for field, expected in expected_metadata.items()
        ):
            raise ValueError("original semantic response identity conflicts with frozen profile")
    except CoverageRefusedError:
        raise
    except (ValueError, TypeError, RecursionError, OverflowError) as error:
        raise CoverageRefusedError(CoverageRefusalReason.UNSUPPORTED) from error
