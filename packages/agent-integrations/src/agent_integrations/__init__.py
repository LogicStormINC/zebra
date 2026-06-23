"""Provider integrations for Zebra Agent."""

from agent_integrations.openai_compatible import (
    OpenAICompatibleModelGateway,
    build_model_gateway,
)
from agent_integrations.scm import (
    GitHubPullRequestConfig,
    GitHubPullRequestGateway,
    GitHubPullRequestPayload,
    LocalOnlyPullRequestGateway,
    PullRequestGateway,
    PullRequestPlan,
    PullRequestRequest,
    ScmIntegrationError,
    ScmUnavailableError,
    build_pull_request_gateway,
)

__all__ = [
    "LocalOnlyPullRequestGateway",
    "PullRequestGateway",
    "GitHubPullRequestConfig",
    "GitHubPullRequestGateway",
    "GitHubPullRequestPayload",
    "OpenAICompatibleModelGateway",
    "PullRequestPlan",
    "PullRequestRequest",
    "ScmIntegrationError",
    "ScmUnavailableError",
    "build_model_gateway",
    "build_pull_request_gateway",
]
