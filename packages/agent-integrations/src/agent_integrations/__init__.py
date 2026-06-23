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
    PullRequestPlan,
    PullRequestRequest,
    ScmIntegrationError,
    ScmUnavailableError,
)

__all__ = [
    "LocalOnlyPullRequestGateway",
    "GitHubPullRequestConfig",
    "GitHubPullRequestGateway",
    "GitHubPullRequestPayload",
    "OpenAICompatibleModelGateway",
    "PullRequestPlan",
    "PullRequestRequest",
    "ScmIntegrationError",
    "ScmUnavailableError",
    "build_model_gateway",
]
