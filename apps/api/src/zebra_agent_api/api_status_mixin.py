from __future__ import annotations

from agent_runtime import build_mcp_capability_inventory, discover_mcp_prompts
from agent_security import SUPPORTED_NETWORK_PROFILES
from agent_storage.postgres.migrations import MIGRATIONS
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_api.responses import ApiResponse


class ApiStatusMixin:
    settings: ZebraAgentSettings

    def get_runtime_capabilities(self) -> ApiResponse:
        platform = getattr(self, "client_platform", None)
        available = platform is not None and all(
            getattr(platform, name, None) is not None
            for name in ("client_sessions", "frontend_capabilities", "client_control_leases")
        )
        from agent_core.ports.client_command_receipts import ClientCommandReceiptReadPort

        return ApiResponse(
            200,
            {
                "contract_version": 1,
                "client_command_segment_precondition_contract_version": 1,
                "schema_version": MIGRATIONS[-1].version,
                "network_profiles": list(SUPPORTED_NETWORK_PROFILES),
                "client_surface_contract_version": 1 if available else 0,
                "client_surface_metadata_contract_version": 1 if available else 0,
                "client_command_receipt_contract_version": int(
                    available
                    and isinstance(
                        getattr(getattr(self, "stores", None), "events", None),
                        ClientCommandReceiptReadPort,
                    )
                ),
                "client_state_admission_contract_version": 1 if available else 0,
                "client_surface_open_contract_version": (
                    1 if available and self.settings.deployment == "cloud" else 0
                ),
            },
        )

    def health(self) -> ApiResponse:
        return ApiResponse(
            status_code=200,
            body={
                "status": "ok",
                "service": "zebra-agent-api",
                "runtime": {
                    "profile": self.settings.profile,
                    "runtime_class": self.settings.runtime.runtime_class,
                    "fallback_allowed": False,
                },
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

    def get_mcp_prompts(self) -> ApiResponse:
        if not self.settings.mcp_servers:
            return ApiResponse(
                status_code=200,
                body={
                    "status": "unconfigured",
                    "configured": False,
                    "available": False,
                    "prompt_count": 0,
                    "prompts": [],
                },
            )
        try:
            prompts = discover_mcp_prompts(self.settings.mcp_servers)
        except ValueError as error:
            return ApiResponse(
                status_code=503,
                body={
                    "status": "unavailable",
                    "configured": True,
                    "available": False,
                    "prompt_count": 0,
                    "prompts": [],
                    "reason": str(error),
                },
            )
        return ApiResponse(
            status_code=200,
            body={
                "status": "available",
                "configured": True,
                "available": True,
                "prompt_count": len(prompts),
                "prompts": [{**prompt.to_safe_mapping(), "available": True} for prompt in prompts],
            },
        )
