"""An opt-in exact prefix never discards the original Host evidence."""

from agent_core.domain.tools import ToolCall, ToolRisk
from agent_tools.contracts import ToolContract
from agent_tools.output_projection import ProjectedToolOutput, ToolOutputProjector


def project_preview(
    projector: ToolOutputProjector | None,
    output: str,
    preview: object,
    *,
    tool_call: ToolCall,
    contract: ToolContract,
) -> ProjectedToolOutput | None:
    if (
        projector is None
        or contract.risk is not ToolRisk.READ
        or not isinstance(preview, str)
        or not 0 < len(preview) <= 12000
        or len(preview) >= len(output)
        or not output.startswith(preview)
    ):
        return None
    return projector.project_text(
        output,
        artifact_name=f"host-output-{tool_call.tool_call_id}.txt",
        small_output=preview,
        provenance={"route": "host_tool_gateway", "tool_name": contract.name},
    )
