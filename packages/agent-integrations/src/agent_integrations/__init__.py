"""Provider integrations for Zebra Agent."""

from agent_integrations.openai_compatible import (
    OpenAICompatibleModelGateway,
    build_model_gateway,
)

__all__ = [
    "OpenAICompatibleModelGateway",
    "build_model_gateway",
]
