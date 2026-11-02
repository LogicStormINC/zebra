"""Public identities stay stable; narrow readers avoid full application bootstrap."""

# ruff: noqa: F405 -- TYPE_CHECKING exports define public types.
from importlib import import_module as _import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._public_exports import *  # noqa: F403
__all__ = [
    "DEEPSEEK_PROFILES",
    "DEEPSEEK_BETA_PROFILES",
    "DeepSeekModelProfile",
    "DeepSeekBetaGateway",
    "DeepSeekBetaProfile",
    "DeepSeekBetaTextResult",
    "DeepSeekProfileRouter",
    "DeepSeekResponsesModelGateway",
    "DeepSeekStrictToolResult",
    "LocalOnlyPullRequestGateway",
    "PullRequestGateway",
    "GitHubPullRequestConfig",
    "GitHubHttpPullRequestTransport",
    "GitHubAppCredentialBinding",
    "GitHubAppCredentialBroker",
    "GitHubAppInstallationToken",
    "GitHubAppTokenTransport",
    "ConfiguredHmacHostCredentialResolver",
    "GitHubPullRequestGateway",
    "GitHubPullRequestPayload",
    "GitHubProxyPullRequestTransport",
    "GitHubPullRequestTransport",
    "OpenAICompatibleModelGateway",
    "ModelProviderSettings",
    "ScmProviderSettings",
    "RedisLiveEventError",
    "RedisCommittedEventPublisher",
    "RedisLiveEventFanout",
    "RedisAgentMemoryConfig",
    "RedisAgentMemoryGateway",
    "ModelProviderError",
    "Mem0AgentMemoryGateway",
    "Mem0GatewayConfig",
    "Mem0ProviderRefLookup",
    "PullRequestPlan",
    "PullRequestRequest",
    "ScmIntegrationError",
    "ScmProxyRequest",
    "ScmProxyResponse",
    "ScmHttpProxyTransport",
    "ScmProxyTransport",
    "ScmUnavailableError",
    "HttpScheduleAuthorityRevalidator",
    "ScheduleGrantExchangeSettings",
    "ResolvedDeepSeekInvocation",
    "build_model_gateway",
    "build_deepseek_beta_gateway",
    "build_pull_request_gateway",
    "build_github_pull_request_proxy_request",
    "deepseek_profile",
    "encode_owner_id",
    "encode_mem0_namespace",
]
_EXPORTS = {
    "DeepSeekBetaGateway": ("agent_integrations.deepseek_beta", "DeepSeekBetaGateway"),
    "DeepSeekStrictToolResult": ("agent_integrations.deepseek_beta", "DeepSeekStrictToolResult"),
    "build_deepseek_beta_gateway": (
        "agent_integrations.deepseek_beta",
        "build_deepseek_beta_gateway",
    ),
    "DEEPSEEK_BETA_PROFILES": (
        "agent_integrations.deepseek_beta_profiles",
        "DEEPSEEK_BETA_PROFILES",
    ),
    "DeepSeekBetaProfile": ("agent_integrations.deepseek_beta_profiles", "DeepSeekBetaProfile"),
    "DeepSeekBetaTextResult": (
        "agent_integrations.deepseek_beta_results",
        "DeepSeekBetaTextResult",
    ),
    "DEEPSEEK_PROFILES": ("agent_integrations.deepseek_profiles", "DEEPSEEK_PROFILES"),
    "DeepSeekModelProfile": ("agent_integrations.deepseek_profiles", "DeepSeekModelProfile"),
    "DeepSeekProfileRouter": ("agent_integrations.deepseek_profiles", "DeepSeekProfileRouter"),
    "ResolvedDeepSeekInvocation": (
        "agent_integrations.deepseek_profiles",
        "ResolvedDeepSeekInvocation",
    ),
    "deepseek_profile": ("agent_integrations.deepseek_profiles", "deepseek_profile"),
    "DeepSeekResponsesModelGateway": (
        "agent_integrations.deepseek_responses",
        "DeepSeekResponsesModelGateway",
    ),
    "GitHubHttpPullRequestTransport": (
        "agent_integrations.github",
        "GitHubHttpPullRequestTransport",
    ),
    "GitHubAppCredentialBinding": ("agent_integrations.github_app", "GitHubAppCredentialBinding"),
    "GitHubAppCredentialBroker": ("agent_integrations.github_app", "GitHubAppCredentialBroker"),
    "GitHubAppInstallationToken": ("agent_integrations.github_app", "GitHubAppInstallationToken"),
    "GitHubAppTokenTransport": ("agent_integrations.github_app", "GitHubAppTokenTransport"),
    "ConfiguredHmacHostCredentialResolver": (
        "agent_integrations.host_credentials",
        "ConfiguredHmacHostCredentialResolver",
    ),
    "Mem0AgentMemoryGateway": ("agent_integrations.mem0", "Mem0AgentMemoryGateway"),
    "Mem0GatewayConfig": ("agent_integrations.mem0", "Mem0GatewayConfig"),
    "Mem0ProviderRefLookup": ("agent_integrations.mem0", "Mem0ProviderRefLookup"),
    "encode_mem0_namespace": ("agent_integrations.mem0", "encode_mem0_namespace"),
    "ModelProviderError": ("agent_integrations.model_errors", "ModelProviderError"),
    "OpenAICompatibleModelGateway": (
        "agent_integrations.openai_compatible",
        "OpenAICompatibleModelGateway",
    ),
    "build_model_gateway": ("agent_integrations.openai_compatible", "build_model_gateway"),
    "ModelProviderSettings": ("agent_integrations.provider_settings", "ModelProviderSettings"),
    "ScmProviderSettings": ("agent_integrations.provider_settings", "ScmProviderSettings"),
    "RedisAgentMemoryConfig": ("agent_integrations.redis_agent_memory", "RedisAgentMemoryConfig"),
    "RedisAgentMemoryGateway": ("agent_integrations.redis_agent_memory", "RedisAgentMemoryGateway"),
    "encode_owner_id": ("agent_integrations.redis_agent_memory", "encode_owner_id"),
    "RedisCommittedEventPublisher": (
        "agent_integrations.redis_live_fanout",
        "RedisCommittedEventPublisher",
    ),
    "RedisLiveEventError": ("agent_integrations.redis_live_fanout", "RedisLiveEventError"),
    "RedisLiveEventFanout": ("agent_integrations.redis_live_fanout", "RedisLiveEventFanout"),
    "HttpScheduleAuthorityRevalidator": (
        "agent_integrations.schedule_grant_exchange",
        "HttpScheduleAuthorityRevalidator",
    ),
    "ScheduleGrantExchangeSettings": (
        "agent_integrations.schedule_grant_exchange",
        "ScheduleGrantExchangeSettings",
    ),
    "GitHubProxyPullRequestTransport": (
        "agent_integrations.scm",
        "GitHubProxyPullRequestTransport",
    ),
    "GitHubPullRequestConfig": ("agent_integrations.scm", "GitHubPullRequestConfig"),
    "GitHubPullRequestGateway": ("agent_integrations.scm", "GitHubPullRequestGateway"),
    "GitHubPullRequestPayload": ("agent_integrations.scm", "GitHubPullRequestPayload"),
    "GitHubPullRequestTransport": ("agent_integrations.scm", "GitHubPullRequestTransport"),
    "LocalOnlyPullRequestGateway": ("agent_integrations.scm", "LocalOnlyPullRequestGateway"),
    "PullRequestGateway": ("agent_integrations.scm", "PullRequestGateway"),
    "PullRequestPlan": ("agent_integrations.scm", "PullRequestPlan"),
    "PullRequestRequest": ("agent_integrations.scm", "PullRequestRequest"),
    "build_pull_request_gateway": ("agent_integrations.scm", "build_pull_request_gateway"),
    "ScmIntegrationError": ("agent_integrations.scm_errors", "ScmIntegrationError"),
    "ScmUnavailableError": ("agent_integrations.scm_errors", "ScmUnavailableError"),
    "ScmProxyRequest": ("agent_integrations.scm_proxy", "ScmProxyRequest"),
    "ScmProxyResponse": ("agent_integrations.scm_proxy", "ScmProxyResponse"),
    "ScmProxyTransport": ("agent_integrations.scm_proxy", "ScmProxyTransport"),
    "build_github_pull_request_proxy_request": (
        "agent_integrations.scm_proxy",
        "build_github_pull_request_proxy_request",
    ),
    "ScmHttpProxyTransport": ("agent_integrations.scm_proxy_http", "ScmHttpProxyTransport"),
}


def __getattr__(name: str) -> object:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module, symbol = _EXPORTS[name]
    value = getattr(_import_module(module, __name__), symbol)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
