"""Private request reconstruction guard (W5-DSH-01, Wave 5 Phase 1).

Before every actual provider dispatch the guard compares the request
envelope against an independently derived durable reconstruction:

- conversation digest: the actual non-system messages (roles/content plus
  tool-call identity) must equal the durable conversation rebuild for that
  dispatch step (repair/fallback dispatches reuse the same envelope; the
  sanctioned compaction transform is the only skip boundary);
- system prompt digest: the actual system messages (excluding deterministic
  internal repair markers) must equal the durable system prompt independently
  built from the frozen Task facts at attempt start;
- tool schema digest: the actual tool set must equal the durable grant set;
- media digest: the actual media inputs must equal the durable task inputs.

The model-config axis is enforced by the existing fail-closed task-model
drift check (``persisted_task_model_id``); its digest is recorded privately
here. Only digests and coordinates are persisted; raw prompts/schemas/grants
never leave the harness.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from hashlib import sha256
from typing import Any

from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.model_media import ModelMediaInput
from agent_core.domain.modeling import ModelInvocationPolicy, ModelToolDefinition
from agent_core.harness.required_tool_request import selected_model_tools


class ReconstructionMismatchError(RuntimeError):
    """The actual request envelope differs from the durable reconstruction."""


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest_text(parts: tuple[str, ...]) -> str:
    return digest_json(list(parts))


def digest_json(value: object) -> str:
    """Canonical structured-envelope digest: exact JSON framing with named
    fields, so content boundaries can never collide structurally."""
    return "sha256:" + sha256(canonical_json(value).encode("utf-8")).hexdigest()


# Explicit absence digest for the Phase-1 no-resource-manifest state, so the
# durable coordinate is populated and auditable without inventing FinOS
# manifest semantics.
NO_RESOURCE_MANIFEST_DIGEST = digest_text(("resource-manifest:absent",))


def conversation_digest(
    messages: list[SessionMessage] | tuple[SessionMessage, ...],
) -> str:
    """Canonical structured envelope over the non-system conversation:
    roles/content, assistant tool-call identity + arguments + provider
    presentation, tool message call ids + result status, and reasoning."""
    envelope: list[dict[str, object]] = []
    for message in messages:
        if message.role is MessageRole.SYSTEM:
            continue
        item: dict[str, object] = {
            "role": message.role.value,
            "content": message.content or "",
        }
        if message.role is MessageRole.ASSISTANT:
            item["tool_calls"] = [
                {
                    "name": tool_call.name,
                    "tool_call_id": str(tool_call.tool_call_id),
                    "arguments": tool_call.arguments,
                    "provider_call_id": tool_call.provider_call_id,
                    "provider_tool_name": tool_call.provider_tool_name,
                    "provider_arguments": tool_call.provider_arguments,
                }
                for tool_call in (message.tool_calls or ())
            ]
        elif message.role is MessageRole.TOOL:
            item["tool_call_id"] = message.tool_call_id or ""
            item["tool_result_status"] = (message.metadata or {}).get("tool_result_status")
        if message.provider_reasoning_content:
            item["provider_reasoning_content"] = message.provider_reasoning_content
        envelope.append(item)
    return digest_json(envelope)


def system_prompt_digest(
    messages: list[SessionMessage] | tuple[SessionMessage, ...],
) -> str:
    return digest_json(
        [
            {"content": message.content or ""}
            for message in messages
            if message.role is MessageRole.SYSTEM
        ]
    )


def stable_system_messages(
    messages: list[SessionMessage] | tuple[SessionMessage, ...],
) -> list[SessionMessage]:
    """System messages that belong to the stable request envelope.

    Harness-generated runtime observations (missing-evidence observation,
    no-progress convergence observation, plan contract observation, validator
    correction instruction) are deterministic guidance derived from the
    durable evidence/plan state, not external request content. They are
    excluded from the stable envelope digest so in-attempt correction
    dispatches reconstruct exactly; the durable invariant still guards the
    stable prompt, tool grant, model configuration, media and conversation.
    """
    return [
        message
        for message in messages
        if message.role is MessageRole.SYSTEM and not _is_runtime_observation(message)
    ]


def _is_runtime_observation(message: SessionMessage) -> bool:
    metadata = message.metadata or {}
    if metadata.get("missing_completion_evidence") is not None:
        return True
    if metadata.get("validator_correction") is True:
        return True
    if metadata.get("required_plan_nudge") is True:
        return True
    content = message.content or ""
    return (
        content.startswith("Runtime completion-evidence observation: ")
        or content.startswith("Runtime convergence observation: ")
        or content.startswith("Runtime contract observation: ")
    )


def tool_schema_digest(tools: tuple[ModelToolDefinition, ...] | list[Any]) -> str:
    schemas: list[dict[str, object]] = []
    for tool in tools:
        if isinstance(tool, ModelToolDefinition):
            schemas.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
            )
        else:
            schemas.append(_coerce_tool_mapping(tool))
    return digest_json(schemas)


def media_inputs_digest(
    media_inputs: tuple[ModelMediaInput, ...],
) -> str:
    return digest_json(
        [
            {
                "artifact_id": str(media.artifact_id),
                "media_type": media.media_type,
                "sha256": media.sha256,
                "size_bytes": media.size_bytes,
                "display_name": media.display_name,
                "ordinal": media.ordinal,
                "source_message_id": str(media.source_message_id),
            }
            for media in media_inputs
        ]
    )


def model_config_digest(basis: str) -> str:
    return digest_json(basis)


def invocation_policy_digest(policy: ModelInvocationPolicy | None) -> str:
    return digest_json(
        None
        if policy is None
        else {
            "role": policy.role.value,
            "thinking_mode": policy.thinking_mode.value,
            "reasoning_effort": (
                policy.reasoning_effort.value if policy.reasoning_effort is not None else None
            ),
            "tool_choice": policy.tool_choice.value,
            "max_output_tokens": policy.max_output_tokens,
        }
    )


def _gateway_model_basis(gateway: object) -> str | None:
    if gateway is None:
        return None
    public = getattr(gateway, "model_config_basis", None)
    if isinstance(public, str) and public.strip():
        return public.strip()
    provider = getattr(gateway, "provider", None)
    if provider is None:
        provider = getattr(gateway, "_provider", None)
    if provider is None:
        provider = getattr(gateway, "_provider_name", None)
    model_name = getattr(gateway, "model_name", None)
    if model_name is None:
        model_name = getattr(gateway, "_model_name", None)
    if not isinstance(provider, str) or not isinstance(model_name, str):
        return None
    return f"{provider}:{model_name}"


def _coerce_tool_mapping(tool: Any) -> dict[str, object]:
    name = getattr(tool, "name", None)
    schema = getattr(tool, "schema", None) or getattr(tool, "input_schema", None)
    return {"name": name, "schema": schema}


class RequestReconstruction:
    """Durable reconstruction expectation for one attempt's dispatches."""

    def __init__(
        self,
        *,
        stable_task_id: str,
        attempt_id: str,
        turn_id: str,
        goal_revision: int = 1,
        plan_revision: int = 1,
        messages_rebuild: Callable[[], list[SessionMessage] | None] | None = None,
        step_envelope: (
            Callable[
                [str, bool, tuple[str, ...]],
                tuple[str, tuple[ModelToolDefinition, ...], str],
            ]
            | None
        ) = None,
        system_prompt_digest: str | None = None,
        tool_schema_digest: str | None = None,
        media_digest: str | None = None,
        model_config_digest: str | None = None,
        invocation_policy_digest: str | None = None,
        resource_manifest_digest: str | None = None,
    ) -> None:
        self.stable_task_id = stable_task_id
        self.attempt_id = attempt_id
        self.turn_id = turn_id
        self.goal_revision = goal_revision
        self.plan_revision = plan_revision
        self.step_id: str | None = None
        self._messages_rebuild = messages_rebuild
        self._step_envelope = step_envelope
        self.system_prompt_digest = system_prompt_digest
        self.tool_schema_digest = tool_schema_digest
        self.media_digest = media_digest
        self.model_config_digest = model_config_digest
        self.invocation_policy_digest = invocation_policy_digest
        self.resource_manifest_digest = resource_manifest_digest

    def verify(
        self,
        messages: list[SessionMessage],
        tools: tuple[ModelToolDefinition, ...],
        *,
        media_inputs: tuple[ModelMediaInput, ...] = (),
        gateway: object | None = None,
        invocation_policy: ModelInvocationPolicy | None = None,
        step_id: str | None = None,
        step_kind: str = "initial",
        allow_tools: bool = True,
        required_tool_names: tuple[str, ...] = (),
        plan_revision: int | None = None,
    ) -> dict[str, object]:
        if step_id is not None:
            self.step_id = step_id
        if plan_revision is not None:
            self.plan_revision = plan_revision
        actual_conversation = conversation_digest(messages)
        actual_system = system_prompt_digest(stable_system_messages(messages))
        actual_tools = tool_schema_digest(tools)
        actual_media = media_inputs_digest(media_inputs)
        rebuilt = self._messages_rebuild() if self._messages_rebuild is not None else None
        if rebuilt is not None:
            if actual_conversation != conversation_digest(rebuilt):
                raise ReconstructionMismatchError(
                    "actual conversation content differs from the durable "
                    "reconstruction for this dispatch"
                )
        expected_system = self.system_prompt_digest
        expected_tools = None
        expected_invocation = self.invocation_policy_digest
        if self._step_envelope is not None:
            expected_system, expected_tools, expected_invocation = self._step_envelope(
                step_kind, allow_tools, required_tool_names
            )
        elif not allow_tools:
            expected_tools = selected_model_tools(
                _empty_available_tools(),
                allow_tools=False,
                required_names=(),
            )
        if expected_system is not None:
            if actual_system != expected_system:
                raise ReconstructionMismatchError(
                    "actual system prompt differs from the durable reconstruction"
                )
        if expected_tools is None:
            expected_tools_digest = self.tool_schema_digest
        else:
            expected_tools_digest = tool_schema_digest(expected_tools)
        if expected_tools_digest is not None:
            if actual_tools != expected_tools_digest:
                raise ReconstructionMismatchError(
                    "actual tool schema set differs from the durable grant set"
                )
        if self.media_digest is not None:
            if actual_media != self.media_digest:
                raise ReconstructionMismatchError(
                    "actual media inputs differ from the durable task inputs"
                )
        if self.model_config_digest is not None:
            basis = _gateway_model_basis(gateway)
            if basis is None:
                raise ReconstructionMismatchError(
                    "guarded gateway cannot supply a safe model identity"
                )
            if model_config_digest(basis) != self.model_config_digest:
                raise ReconstructionMismatchError(
                    "actual model config differs from the durable model facts"
                )
        actual_invocation = invocation_policy_digest(invocation_policy)
        if expected_invocation is not None and actual_invocation != expected_invocation:
            raise ReconstructionMismatchError(
                "actual invocation policy differs from the durable dispatch constraints"
            )
        return {
            "stable_task_id": self.stable_task_id,
            "attempt_id": self.attempt_id,
            "turn_id": self.turn_id,
            "goal_revision": self.goal_revision,
            "plan_revision": self.plan_revision,
            "step_id": self.step_id,
            "messages_digest": actual_conversation,
            "system_prompt_digest": actual_system,
            "tool_schema_digest": actual_tools,
            "model_config_digest": self.model_config_digest,
            "invocation_policy_digest": actual_invocation,
            "resource_manifest_digest": self.resource_manifest_digest,
        }


def prepare_guarded_dispatch(
    reconstruction: RequestReconstruction | None,
    messages: list[SessionMessage],
    tools: tuple[ModelToolDefinition, ...],
    *,
    media_inputs: tuple[ModelMediaInput, ...] = (),
    gateway: object | None = None,
    invocation_policy: ModelInvocationPolicy | None = None,
    response_repair_limit: int = 0,
    step_id: str | None = None,
    step_kind: str = "initial",
    allow_tools: bool = True,
    required_tool_names: tuple[str, ...] = (),
    plan_revision: int | None = None,
) -> tuple[dict[str, object], int]:
    """Shared pre-dispatch seam: verify the envelope and disable internal
    response repair under the guard (repairs change the request envelope and
    therefore fail/suspend through the classified path instead)."""
    if reconstruction is None:
        return {}, response_repair_limit
    return (
        reconstruction.verify(
            messages,
            tools,
            media_inputs=media_inputs,
            gateway=gateway,
            invocation_policy=invocation_policy,
            step_id=step_id,
            step_kind=step_kind,
            allow_tools=allow_tools,
            required_tool_names=required_tool_names,
            plan_revision=plan_revision,
        ),
        0,
    )


def _empty_available_tools() -> tuple[ModelToolDefinition, ...]:
    return ()
