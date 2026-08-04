from __future__ import annotations

from agent_core.domain.model_media import ModelInputModality
from agent_integrations.openai_model_profiles import resolve_model_profile
from agent_runtime import build_mcp_capability_inventory, discover_mcp_prompts
from zebra_agent_config import (
    MODEL_CATALOG_SCHEMA,
    ZebraAgentSettings,
    catalog_for_settings,
)

from zebra_agent_api.responses import ApiResponse


class ApiStatusMixin:
    settings: ZebraAgentSettings

    def health(self) -> ApiResponse:
        try:
            default_model = catalog_for_settings(self.settings).select().settings
            native_image_understanding = ModelInputModality.IMAGE in resolve_model_profile(
                default_model.profile_id,
                provider=default_model.provider,
                model=default_model.model,
            ).input_modalities
        except ValueError:
            native_image_understanding = False
        return ApiResponse(
            status_code=200,
            body={
                "status": "ok",
                "service": "zebra-agent-api",
                "runtime": {
                    "profile": self.settings.profile,
                    "runtime_class": self.settings.runtime.runtime_class,
                    "fallback_allowed": False,
                    "build_commit": self.settings.build_commit,
                    "task_image_attachments": True,
                    "native_image_understanding": native_image_understanding,
                    "final_message_identity": True,
                    "artifact_output_contract": True,
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

    def get_model_capabilities(self) -> ApiResponse:
        catalog = catalog_for_settings(self.settings)
        return ApiResponse(
            status_code=200,
            body={
                "schema_version": MODEL_CATALOG_SCHEMA,
                "default_id": catalog.default_id,
                "models": [entry.to_public_mapping() for entry in catalog.entries],
            },
        )

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
