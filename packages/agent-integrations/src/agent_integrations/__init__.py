"""Provider integrations for Zebra Agent."""

from agent_integrations.github import GitHubHttpPullRequestTransport
from agent_integrations.openai_compatible import (
    OpenAICompatibleModelGateway,
    build_model_gateway,
)
from agent_integrations.scm import (
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

__all__ = [
    "LocalOnlyPullRequestGateway",
    "PullRequestGateway",
    "GitHubPullRequestConfig",
    "GitHubHttpPullRequestTransport",
    "GitHubPullRequestGateway",
    "GitHubPullRequestPayload",
    "GitHubPullRequestTransport",
    "OpenAICompatibleModelGateway",
    "PullRequestPlan",
    "PullRequestRequest",
    "ScmIntegrationError",
    "ScmUnavailableError",
    "build_model_gateway",
    "build_pull_request_gateway",
]
