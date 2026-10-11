"""Bounded semantic gateway invocation; durable callbacks require explicit composition."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

from agent_core.application.coverage_semantic import semantic_check, validate_semantic_result
from agent_core.domain.coverage_contracts import CoverageRefusalReason as Reason
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_core.domain.coverage_execution import CoverageObservation, PublishedCoverageCheck
from agent_core.domain.coverage_validation import CoverageUnitKey
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCompletion,
    ModelInvocationPolicy,
    ModelRole,
    ModelToolChoice,
)
from agent_core.ports.model_gateway import ModelGatewayPort

from agent_integrations.coverage_snapshot_invocation import unique_object

MAX_RESPONSE_BYTES = 65536


def _reject_constant(value: str) -> object:
    raise ValueError(f"invalid JSON constant: {value}")


class SemanticCoverageModel:
    """Callbacks raise on refusal; record_response receives the full completion/usage.

    The injected gateway must disable internal retries. This adapter invokes it once
    and refuses responses reporting retries or repairs, never recovering silently.
    """

    def __init__(
        self,
        *,
        gateway: ModelGatewayPort | None = None,
        model_profile: str,
        check_authority: Callable[[], None],
        reserve_call: Callable[[], None] | None = None,
        record_response: Callable[[ModelCompletion], None] | None = None,
        invoke_or_replay: Callable[[list[SessionMessage], ModelInvocationPolicy], ModelCompletion]
        | None = None,
    ) -> None:
        self._definition = semantic_check(model_profile)
        if (
            not callable(check_authority)
            or (
                invoke_or_replay is None
                and (gateway is None or not callable(reserve_call) or not callable(record_response))
            )
            or (
                invoke_or_replay is not None
                and (
                    not callable(invoke_or_replay)
                    or any(value is not None for value in (gateway, reserve_call, record_response))
                )
            )
        ):
            raise ValueError(
                "coverage model requires authority, reservation and response callbacks"
            )
        self._gateway = gateway
        self._check_authority = check_authority
        self._reserve_call = reserve_call
        self._record_response = record_response
        self._invoke_or_replay = invoke_or_replay

    def _authorize(self) -> None:
        try:
            self._check_authority()
        except CoverageRefusedError:
            raise
        except Exception as error:
            raise CoverageRefusedError(Reason.AUTHORITY_INVALID) from error

    def __call__(
        self, definition: PublishedCoverageCheck, key: CoverageUnitKey, bodies: dict[str, str]
    ) -> CoverageObservation:
        try:
            # Raw key fields preserve illicit attributes inserted without validation.
            if key.__pydantic_extra__:
                raise ValueError("unsupported extra unit key attributes")
            validated_key = CoverageUnitKey.model_validate(key.__dict__)
            check = self._definition.contract_check
            if (
                definition != self._definition
                or validated_key.kind != "part"
                or validated_key.check_id != check.id
                or validated_key.check_version != check.version
                or validated_key.definition_digest != check.definition_digest
                or set(bodies) != {validated_key.part_id}
                or any(not isinstance(body, str) for body in bodies.values())
                or sum(len(body) for body in bodies.values()) > self._definition.max_part_characters
            ):
                raise ValueError("unsupported semantic definition, unit or source")
            source = dict(bodies)
            user_json = json.dumps(
                {"key": validated_key.model_dump(mode="json"), "bodies": source},
                ensure_ascii=False,
                allow_nan=False,
            )
            messages = [
                SessionMessage(
                    message_id=new_message_id(),
                    role=role,
                    content=content,
                    created_at=datetime.now(UTC),
                )
                for role, content in (
                    (MessageRole.SYSTEM, self._definition.instructions),
                    (MessageRole.USER, user_json),
                )
            ]
        except (ValueError, TypeError) as error:
            raise CoverageRefusedError(Reason.UNSUPPORTED) from error

        try:
            self._authorize()
            policy = ModelInvocationPolicy(
                role=ModelRole.REVIEWER,
                profile_id=self._definition.model_profile,
                tool_choice=ModelToolChoice.NONE,
                max_output_tokens=8192,
            )
            if self._invoke_or_replay is not None:
                response = self._invoke_or_replay(messages, policy)
            else:
                assert self._reserve_call is not None and self._record_response is not None
                self._reserve_call()
                self._authorize()
                response = cast(Any, self._gateway).complete(
                    messages,
                    tools=(),
                    invocation_policy=policy,
                )
                # Legacy usage recording precedes metadata/content refusal.
                self._record_response(response)
            self._authorize()
        except CoverageRefusedError:
            raise
        except Exception as error:
            raise CoverageRefusedError(Reason.UNRESOLVED_FAILURE) from error

        return validate_semantic_completion(self._definition, validated_key, source, response)


def validate_semantic_completion(
    definition: PublishedCoverageCheck,
    key: CoverageUnitKey,
    bodies: dict[str, str],
    response: ModelCompletion,
) -> CoverageObservation:
    """Side-effect-free final metadata, JSON and source validation shared with replay."""
    try:
        if (
            not isinstance(response, ModelCompletion)
            or response.assistant_message.role is not MessageRole.ASSISTANT
            or response.call_metadata.profile_id != definition.model_profile
            or response.tool_calls
            or response.assistant_message.tool_calls
            or response.call_metadata.finish_reason not in {"stop", "end_turn", "completed"}
            or response.call_metadata.retry_count
            or response.call_metadata.response_repair_count
        ):
            raise ValueError("unsupported semantic model response metadata")
        text = response.assistant_message.content
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise ValueError("unsupported semantic response size or encoding")
        result = json.loads(text, object_pairs_hook=unique_object, parse_constant=_reject_constant)
        if not isinstance(result, dict):
            raise ValueError("semantic response must be a single JSON object")
    except (ValueError, TypeError, RecursionError) as error:
        raise CoverageRefusedError(Reason.UNSUPPORTED) from error
    return validate_semantic_result(definition, key, bodies, result)
