from __future__ import annotations

from pathlib import Path

from zebra_agent_api.memory_inventory_read import (
    read_tenant_memory_inventory,
    read_tenant_memory_queue,
    read_tenant_memory_queue_summary,
    read_user_memory_inventory,
    read_user_memory_queue,
    read_user_memory_queue_summary,
)
from zebra_agent_api.responses import ApiResponse


class ScopedMemoryReadMixin:
    database_path: Path

    def get_user_memory(self, user_id: str) -> ApiResponse:
        return ApiResponse(
            status_code=200,
            body={
                "user_id": user_id,
                "memories": read_user_memory_inventory(
                    database_path=self.database_path,
                    user_id=user_id,
                ),
            },
        )

    def get_user_memory_queue(self, user_id: str) -> ApiResponse:
        return ApiResponse(
            status_code=200,
            body={
                "user_id": user_id,
                "memories": read_user_memory_queue(
                    database_path=self.database_path,
                    user_id=user_id,
                ),
            },
        )

    def get_user_memory_queue_summary(self, user_id: str) -> ApiResponse:
        return ApiResponse(
            status_code=200,
            body={
                "user_id": user_id,
                **read_user_memory_queue_summary(
                    database_path=self.database_path,
                    user_id=user_id,
                ),
            },
        )

    def get_tenant_memory(self, tenant_id: str) -> ApiResponse:
        return ApiResponse(
            status_code=200,
            body={
                "tenant_id": tenant_id,
                "memories": read_tenant_memory_inventory(
                    database_path=self.database_path,
                    tenant_id=tenant_id,
                ),
            },
        )

    def get_tenant_memory_queue(self, tenant_id: str) -> ApiResponse:
        return ApiResponse(
            status_code=200,
            body={
                "tenant_id": tenant_id,
                "memories": read_tenant_memory_queue(
                    database_path=self.database_path,
                    tenant_id=tenant_id,
                ),
            },
        )

    def get_tenant_memory_queue_summary(self, tenant_id: str) -> ApiResponse:
        return ApiResponse(
            status_code=200,
            body={
                "tenant_id": tenant_id,
                **read_tenant_memory_queue_summary(
                    database_path=self.database_path,
                    tenant_id=tenant_id,
                ),
            },
        )
