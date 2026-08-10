"""Provider integrations for Zebra Agent."""

from agent_integrations.deepseek_beta import (
    DeepSeekBetaGateway,
    DeepSeekStrictToolResult,
    build_deepseek_beta_gateway,
)
from agent_integrations.deepseek_beta_profiles import (
    DEEPSEEK_BETA_PROFILES,
    DeepSeekBetaProfile,
)
from agent_integrations.deepseek_beta_results import DeepSeekBetaTextResult
from agent_integrations.deepseek_profiles import (
    DEEPSEEK_PROFILES,
    DeepSeekModelProfile,
    DeepSeekProfileRouter,
    ResolvedDeepSeekInvocation,
    deepseek_profile,
)
from agent_integrations.github import GitHubHttpPullRequestTransport
from agent_integrations.github_app import (
    GitHubAppCredentialBinding,
    GitHubAppCredentialBroker,
    GitHubAppInstallationToken,
    GitHubAppTokenTransport,
)
from agent_integrations.mem0 import (
    Mem0AgentMemoryGateway,
    Mem0GatewayConfig,
    Mem0ProviderRefLookup,
    encode_mem0_namespace,
)
from agent_integrations.model_errors import ModelProviderError
from agent_integrations.openai_compatible import (
    OpenAICompatibleModelGateway,
    build_model_gateway,
)
from agent_integrations.provider_settings import ModelProviderSettings, ScmProviderSettings
from agent_integrations.redis_live_fanout import (
    RedisCommittedEventPublisher,
    RedisLiveEventError,
    RedisLiveEventFanout,
)
from agent_integrations.scm import (
    GitHubProxyPullRequestTransport,
    GitHubPullRequestConfig,
    GitHubPullRequestGateway,
    GitHubPullRequestPayload,
    GitHubPullRequestTransport,
    LocalOnlyPullRequestGateway,
    PullRequestGateway,
    PullRequestPlan,
    PullRequestRequest,
    build_pull_request_gateway,
)
from agent_integrations.scm_errors import ScmIntegrationError, ScmUnavailableError
from agent_integrations.scm_proxy import (
    ScmProxyRequest,
    ScmProxyResponse,
    ScmProxyTransport,
    build_github_pull_request_proxy_request,
)
from agent_integrations.scm_proxy_http import ScmHttpProxyTransport

__all__ = [
    "DEEPSEEK_PROFILES",
    "DEEPSEEK_BETA_PROFILES",
    "DeepSeekModelProfile",
    "DeepSeekBetaGateway",
    "DeepSeekBetaProfile",
    "DeepSeekBetaTextResult",
    "DeepSeekProfileRouter",
    "DeepSeekStrictToolResult",
    "LocalOnlyPullRequestGateway",
    "PullRequestGateway",
    "GitHubPullRequestConfig",
    "GitHubHttpPullRequestTransport",
    "GitHubAppCredentialBinding",
    "GitHubAppCredentialBroker",
    "GitHubAppInstallationToken",
    "GitHubAppTokenTransport",
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
    "ResolvedDeepSeekInvocation",
    "build_model_gateway",
    "build_deepseek_beta_gateway",
    "build_pull_request_gateway",
    "build_github_pull_request_proxy_request",
    "deepseek_profile",
    "encode_mem0_namespace",
]
