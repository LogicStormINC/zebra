from __future__ import annotations

from dataclasses import dataclass

from agent_core.domain.modeling import (
    ModelContextWindow,
    ModelInvocationPolicy,
    ModelReasoningEffort,
    ModelRole,
    ModelThinkingMode,
    ModelToolChoice,
)

PROFILE_VERSION_OBSERVED_AT = "2026-08-25"


@dataclass(frozen=True)
class DeepSeekModelProfile:
    profile_id: str
    model: str
    roles: frozenset[ModelRole]
    thinking_mode: ModelThinkingMode
    reasoning_effort: ModelReasoningEffort | None
    supports_tools: bool
    context_window: ModelContextWindow
    prompt_version: str = "zebra-deepseek-chat-v2"
    timeout_profile: str = "deepseek-interactive-v1"
    version_observed_at: str = PROFILE_VERSION_OBSERVED_AT


@dataclass(frozen=True)
class ResolvedDeepSeekInvocation:
    profile: DeepSeekModelProfile
    role: ModelRole
    thinking_mode: ModelThinkingMode
    reasoning_effort: ModelReasoningEffort | None
    tool_choice: ModelToolChoice
    max_output_tokens: int


_CONTEXT_WINDOW = ModelContextWindow(
    context_tokens=1_000_000,
    max_output_tokens=393_216,
    reasoning_reserve_tokens=32_768,
    compaction_reserve_tokens=8_192,
    protocol_reserve_tokens=8_192,
)


def _profile(
    profile_id: str,
    model: str,
    roles: tuple[ModelRole, ...],
    thinking_mode: ModelThinkingMode,
    reasoning_effort: ModelReasoningEffort | None,
    *,
    supports_tools: bool,
) -> DeepSeekModelProfile:
    return DeepSeekModelProfile(
        profile_id=profile_id,
        model=model,
        roles=frozenset(roles),
        thinking_mode=thinking_mode,
        reasoning_effort=reasoning_effort,
        supports_tools=supports_tools,
        context_window=_CONTEXT_WINDOW,
    )


DEEPSEEK_PROFILES = (
    _profile(
        "deepseek-v4-flash-executor-v1",
        "deepseek-v4-flash",
        (ModelRole.EXECUTOR,),
        ModelThinkingMode.DISABLED,
        None,
        supports_tools=True,
    ),
    _profile(
        "deepseek-v4-flash-fast-v1",
        "deepseek-v4-flash",
        (ModelRole.CLASSIFIER, ModelRole.SUMMARIZER),
        ModelThinkingMode.DISABLED,
        None,
        supports_tools=False,
    ),
    _profile(
        "deepseek-v4-flash-reasoning-v1",
        "deepseek-v4-flash",
        (ModelRole.ANALYST,),
        ModelThinkingMode.ENABLED,
        ModelReasoningEffort.HIGH,
        supports_tools=False,
    ),
    _profile(
        "deepseek-v4-pro-planner-v1",
        "deepseek-v4-pro",
        (ModelRole.PLANNER,),
        ModelThinkingMode.ENABLED,
        ModelReasoningEffort.MAX,
        supports_tools=False,
    ),
    _profile(
        "deepseek-v4-pro-reviewer-v1",
        "deepseek-v4-pro",
        (ModelRole.REVIEWER,),
        ModelThinkingMode.ENABLED,
        ModelReasoningEffort.HIGH,
        supports_tools=False,
    ),
    _profile(
        "deepseek-v4-pro-executor-v1",
        "deepseek-v4-pro",
        (ModelRole.EXECUTOR,),
        ModelThinkingMode.DISABLED,
        None,
        supports_tools=True,
    ),
)

_PROFILES_BY_ID = {profile.profile_id: profile for profile in DEEPSEEK_PROFILES}
_DEFAULT_PROFILE_BY_ROLE = {
    ModelRole.CLASSIFIER: "deepseek-v4-flash-fast-v1",
    ModelRole.SUMMARIZER: "deepseek-v4-flash-fast-v1",
    ModelRole.ANALYST: "deepseek-v4-flash-reasoning-v1",
    ModelRole.PLANNER: "deepseek-v4-pro-planner-v1",
    ModelRole.REVIEWER: "deepseek-v4-pro-reviewer-v1",
    ModelRole.EXECUTOR: "deepseek-v4-flash-executor-v1",
}


class DeepSeekProfileRouter:
    def __init__(
        self,
        *,
        role_profiles: dict[ModelRole, str] | None = None,
        legacy_executor_model: str | None = None,
    ) -> None:
        self._role_profiles = dict(role_profiles or {})
        self._legacy_executor_model = legacy_executor_model
        for role, profile_id in self._role_profiles.items():
            profile = deepseek_profile(profile_id)
            if role not in profile.roles:
                raise ValueError(f"DeepSeek profile {profile_id} does not support role {role}")

    def resolve(
        self,
        policy: ModelInvocationPolicy,
        *,
        has_tools: bool,
    ) -> ResolvedDeepSeekInvocation:
        profile_id = self._role_profiles.get(
            policy.role,
            _DEFAULT_PROFILE_BY_ROLE[policy.role],
        )
        profile = deepseek_profile(profile_id)
        if (
            policy.role is ModelRole.EXECUTOR
            and self._legacy_executor_model
            and policy.role not in self._role_profiles
        ):
            profile = DeepSeekModelProfile(
                profile_id="deepseek-legacy-executor-v1",
                model=self._legacy_executor_model,
                roles=frozenset({ModelRole.EXECUTOR}),
                thinking_mode=ModelThinkingMode.DISABLED,
                reasoning_effort=None,
                supports_tools=True,
                context_window=_CONTEXT_WINDOW,
            )
        thinking_mode = (
            profile.thinking_mode
            if policy.thinking_mode is ModelThinkingMode.AUTO
            else policy.thinking_mode
        )
        reasoning_effort = policy.reasoning_effort or profile.reasoning_effort
        tool_choice = policy.tool_choice if has_tools else ModelToolChoice.NONE
        _validate_invocation(
            profile,
            has_tools=has_tools,
            thinking_mode=thinking_mode,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
        )
        return ResolvedDeepSeekInvocation(
            profile=profile,
            role=policy.role,
            thinking_mode=thinking_mode,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
            max_output_tokens=policy.max_output_tokens or profile.context_window.max_output_tokens,
        )


def deepseek_profile(profile_id: str) -> DeepSeekModelProfile:
    try:
        return _PROFILES_BY_ID[profile_id]
    except KeyError as exc:
        raise ValueError(f"unknown DeepSeek profile: {profile_id}") from exc


def _validate_invocation(
    profile: DeepSeekModelProfile,
    *,
    has_tools: bool,
    thinking_mode: ModelThinkingMode,
    reasoning_effort: ModelReasoningEffort | None,
    tool_choice: ModelToolChoice,
) -> None:
    if has_tools and not profile.supports_tools:
        raise ValueError(f"DeepSeek profile {profile.profile_id} does not support tools")
    if thinking_mode is ModelThinkingMode.DISABLED and reasoning_effort is not None:
        raise ValueError("DeepSeek reasoning_effort requires thinking enabled")
    if (
        has_tools
        and thinking_mode is ModelThinkingMode.ENABLED
        and tool_choice is ModelToolChoice.REQUIRED
    ):
        raise ValueError("DeepSeek thinking mode does not support tool_choice=required")
    if has_tools and tool_choice is ModelToolChoice.NONE:
        raise ValueError("DeepSeek tool-bearing invocation cannot use tool_choice=none")
    if not has_tools and tool_choice is ModelToolChoice.REQUIRED:
        raise ValueError("DeepSeek tool_choice=required requires advertised tools")
