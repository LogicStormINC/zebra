"""Provider integrations for Zebra Agent."""

from agent_integrations.github import GitHubHttpPullRequestTransport
from agent_integrations.github_app import (
    GitHubAppCredentialBinding,
    GitHubAppCredentialBroker,
    GitHubAppInstallationToken,
    GitHubAppTokenTransport,
)
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
    "PullRequestPlan",
    "PullRequestRequest",
    "ScmIntegrationError",
    "ScmProxyRequest",
    "ScmProxyResponse",
    "ScmHttpProxyTransport",
    "ScmProxyTransport",
    "ScmUnavailableError",
    "build_model_gateway",
    "build_pull_request_gateway",
    "build_github_pull_request_proxy_request",
]
