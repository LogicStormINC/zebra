"""Provider integrations for Zebra Agent."""

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
from agent_integrations.model_errors import ModelProviderError
from agent_integrations.openai_compatible import (
    OpenAICompatibleModelGateway,
    build_model_gateway,
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
    "DeepSeekModelProfile",
    "DeepSeekProfileRouter",
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
    "ModelProviderError",
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
    "build_pull_request_gateway",
    "build_github_pull_request_proxy_request",
    "deepseek_profile",
]
