"""Task-local frozen Chat adapter; strict Coverage retains its source-owned adapter."""

import os
from dataclasses import replace
from typing import Any

import httpx
from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import (
    ModelCompletion,
    ModelContextWindow,
    ModelInvocationPolicy,
    ModelThinkingMode,
    ModelToolDefinition,
)
from agent_core.domain.runtime_assembly import RuntimeAssembly
from agent_core.domain.script_bundle import parse_runtime_assembly

from agent_integrations.deepseek_profiles import ResolvedDeepSeekInvocation
from agent_integrations.openai_compatible import OpenAICompatibleModelGateway
from agent_integrations.request_metadata import ModelRequestMetadata


class BundleModelGateway(OpenAICompatibleModelGateway):
    def __init__(self, assembly: RuntimeAssembly, *, client: httpx.Client | None = None) -> None:
        self._assembly = parse_runtime_assembly(assembly)
        model = self._assembly.bundle.manifest.domains.model.parameters
        profile = self._assembly.provider_profile
        key = os.environ.get(profile.api_key_env, "").strip()
        if not key:
            raise ValueError("BUNDLE_PROVIDER_CREDENTIAL_UNAVAILABLE")
        super().__init__(
            provider_name=profile.provider,
            base_url=profile.base_url,
            api_key=key,
            model_name=model.model,
            max_retries=model.max_retries,
            client=client,
        )

    @property
    def context_window(self) -> ModelContextWindow:
        model = self._assembly.bundle.manifest.domains.model.parameters
        return ModelContextWindow(
            context_tokens=model.context_window_tokens,
            max_output_tokens=model.max_output_tokens,
        )

    def complete(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...] = (),
        invocation_policy: ModelInvocationPolicy | None = None,
        strict_tools: bool = False,
        deadline_s: float | None = None,
    ) -> ModelCompletion:
        # The inherited bounded HTTP path overwrites max_tokens from this policy.
        policy = invocation_policy or ModelInvocationPolicy()
        maximum = self._assembly.bundle.manifest.domains.model.parameters.max_output_tokens
        policy = replace(
            policy, max_output_tokens=min(policy.max_output_tokens or maximum, maximum)
        )
        return super().complete(
            messages,
            tools=tools,
            invocation_policy=policy,
            strict_tools=strict_tools,
            deadline_s=deadline_s,
        )

    def _request_body(
        self,
        messages: list[SessionMessage],
        *,
        tools: tuple[ModelToolDefinition, ...],
        tool_names: tuple[str, ...],
        stream: bool,
        resolved: ResolvedDeepSeekInvocation | None,
        strict_tools: bool,
        invocation_policy: ModelInvocationPolicy | None = None,
    ) -> tuple[dict[str, Any], ModelRequestMetadata | None]:
        policy = invocation_policy or ModelInvocationPolicy()
        if (
            policy.profile_id is not None
            or policy.thinking_mode is not ModelThinkingMode.AUTO
            or policy.reasoning_effort is not None
        ):
            raise ValueError("INCOMPATIBLE_BUNDLE_MODEL_POLICY")
        body, metadata = super()._request_body(
            messages,
            tools=tools,
            tool_names=tool_names,
            stream=stream,
            resolved=resolved,
            strict_tools=strict_tools,
        )
        model = self._assembly.bundle.manifest.domains.model.parameters
        body.update(
            max_tokens=min(
                policy.max_output_tokens or model.max_output_tokens, model.max_output_tokens
            ),
            temperature=model.temperature_milli / 1000,
            tool_choice=policy.tool_choice.value,
        )
        if not tools:
            body.pop("tool_choice")
        return body, metadata
