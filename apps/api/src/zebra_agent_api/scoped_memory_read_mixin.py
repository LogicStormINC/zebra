from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from agent_core.application import confirmed_user_profile
from agent_core.domain.memories import MemoryQuery, MemoryStatus, MemoryVisibility
from agent_storage import ControlPlaneStores

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
    stores: ControlPlaneStores

    def get_user_memory(self, user_id: str) -> ApiResponse:
        return ApiResponse(
            status_code=200,
            body={
                "user_id": user_id,
                "memories": read_user_memory_inventory(
                    database_path=self.database_path,
                    stores=self.stores,
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
                    stores=self.stores,
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
                    stores=self.stores,
                    user_id=user_id,
                ),
            },
        )

    def get_user_memory_profile(self, user_id: str) -> ApiResponse:
        records = tuple(
            self.stores.memories.list(
                MemoryQuery(
                    user_id=user_id,
                    visibility=MemoryVisibility.USER,
                    statuses=(MemoryStatus.CONFIRMED,),
                    limit=500,
                )
            )
        )
        items = confirmed_user_profile(records)
        sections = {
            category: [asdict(item) for item in items if item.category == category]
            for category in ("preference", "background", "goal")
        }
        return ApiResponse(
            status_code=200,
            body={
                "user_id": user_id,
                "profile": sections,
                "memory_count": len(items),
                "derived_from": "confirmed_governed_memory",
            },
        )

    def get_tenant_memory(self, tenant_id: str) -> ApiResponse:
        return ApiResponse(
            status_code=200,
            body={
                "tenant_id": tenant_id,
                "memories": read_tenant_memory_inventory(
                    database_path=self.database_path,
                    stores=self.stores,
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
                    stores=self.stores,
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
                    stores=self.stores,
                    tenant_id=tenant_id,
                ),
            },
        )
