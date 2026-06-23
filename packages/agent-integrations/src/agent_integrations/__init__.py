"""Provider integrations for Zebra Agent."""

from agent_integrations.openai_compatible import (
    OpenAICompatibleModelGateway,
    build_model_gateway,
)
from agent_integrations.scm import (
    LocalOnlyPullRequestGateway,
    PullRequestPlan,
    PullRequestRequest,
    ScmIntegrationError,
    ScmUnavailableError,
)

__all__ = [
    "LocalOnlyPullRequestGateway",
    "OpenAICompatibleModelGateway",
    "PullRequestPlan",
    "PullRequestRequest",
    "ScmIntegrationError",
    "ScmUnavailableError",
    "build_model_gateway",
]
