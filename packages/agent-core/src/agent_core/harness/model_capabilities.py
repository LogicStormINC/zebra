from agent_core.domain.model_media import ModelInputModality
from agent_core.ports.model_gateway import ModelGatewayPort, ModelMediaCapabilityPort


def declared_model_capabilities(
    model_gateway: ModelGatewayPort,
    has_tools: bool,
) -> tuple[str, ...]:
    capabilities = ["text"]
    if has_tools:
        capabilities.append("tools")
    if (
        isinstance(model_gateway, ModelMediaCapabilityPort)
        and ModelInputModality.IMAGE in model_gateway.media_capabilities.input_modalities
    ):
        capabilities.append("image")
    return tuple(capabilities)
