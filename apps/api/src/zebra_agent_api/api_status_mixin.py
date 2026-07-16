from __future__ import annotations

from agent_runtime import build_mcp_capability_inventory
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_api.responses import ApiResponse


class ApiStatusMixin:
    settings: ZebraAgentSettings

    def health(self) -> ApiResponse:
        return ApiResponse(
            status_code=200,
            body={
                "status": "ok",
                "service": "zebra-agent-api",
            },
        )

    def get_mcp_capabilities(self) -> ApiResponse:
        try:
            inventory = build_mcp_capability_inventory(self.settings.mcp_servers)
        except ValueError as error:
            return ApiResponse(
                status_code=503,
                body={
                    "status": "unavailable",
                    "configured": True,
                    "available": False,
                    "server_count": len(self.settings.mcp_servers),
                    "tool_count": 0,
                    "resource_count": 0,
                    "servers": [],
                    "reason": str(error),
                },
            )
        return ApiResponse(status_code=200, body=inventory.to_mapping())
