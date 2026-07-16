from __future__ import annotations

from pathlib import Path

from agent_core.application import MemoryReviewAction

from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_memory_control import (
    preview_session_memory_queue,
    preview_tenant_memory_queue,
    preview_user_memory_queue,
    review_session_memory,
    review_session_memory_bulk,
    review_session_memory_queue,
    review_tenant_memory,
    review_tenant_memory_bulk,
    review_tenant_memory_queue,
    review_user_memory,
    review_user_memory_bulk,
    review_user_memory_queue,
)


class ApiMemoryControlMixin:
    database_path: Path

    def confirm_session_memory(
        self,
        session_id: str,
        memory_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return review_session_memory(
            database_path=self.database_path,
            session_id=session_id,
            memory_id=memory_id,
            payload=payload,
            action=MemoryReviewAction.CONFIRM,
            decision="confirm",
        )

    def expire_session_memory(
        self,
        session_id: str,
        memory_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return review_session_memory(
            database_path=self.database_path,
            session_id=session_id,
            memory_id=memory_id,
            payload=payload,
            action=MemoryReviewAction.EXPIRE,
            decision="expire",
        )

    def bulk_review_session_memory(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return review_session_memory_bulk(
            database_path=self.database_path,
            session_id=session_id,
            payload=payload,
        )

    def review_session_memory_queue(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return review_session_memory_queue(
            database_path=self.database_path,
            session_id=session_id,
            payload=payload,
        )

    def preview_session_memory_queue(
        self,
        session_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return preview_session_memory_queue(
            database_path=self.database_path,
            session_id=session_id,
            payload=payload,
        )

    def confirm_user_memory(
        self,
        user_id: str,
        memory_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return review_user_memory(
            database_path=self.database_path,
            user_id=user_id,
            memory_id=memory_id,
            payload=payload,
            action=MemoryReviewAction.CONFIRM,
            decision="confirm",
        )

    def expire_user_memory(
        self,
        user_id: str,
        memory_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return review_user_memory(
            database_path=self.database_path,
            user_id=user_id,
            memory_id=memory_id,
            payload=payload,
            action=MemoryReviewAction.EXPIRE,
            decision="expire",
        )

    def bulk_review_user_memory(
        self,
        user_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return review_user_memory_bulk(
            database_path=self.database_path,
            user_id=user_id,
            payload=payload,
        )

    def review_user_memory_queue(
        self,
        user_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return review_user_memory_queue(
            database_path=self.database_path,
            user_id=user_id,
            payload=payload,
        )

    def preview_user_memory_queue(
        self,
        user_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return preview_user_memory_queue(
            database_path=self.database_path,
            user_id=user_id,
            payload=payload,
        )

    def confirm_tenant_memory(
        self,
        tenant_id: str,
        memory_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return review_tenant_memory(
            database_path=self.database_path,
            tenant_id=tenant_id,
            memory_id=memory_id,
            payload=payload,
            action=MemoryReviewAction.CONFIRM,
            decision="confirm",
        )

    def expire_tenant_memory(
        self,
        tenant_id: str,
        memory_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return review_tenant_memory(
            database_path=self.database_path,
            tenant_id=tenant_id,
            memory_id=memory_id,
            payload=payload,
            action=MemoryReviewAction.EXPIRE,
            decision="expire",
        )

    def bulk_review_tenant_memory(
        self,
        tenant_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return review_tenant_memory_bulk(
            database_path=self.database_path,
            tenant_id=tenant_id,
            payload=payload,
        )

    def review_tenant_memory_queue(
        self,
        tenant_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return review_tenant_memory_queue(
            database_path=self.database_path,
            tenant_id=tenant_id,
            payload=payload,
        )

    def preview_tenant_memory_queue(
        self,
        tenant_id: str,
        payload: dict[str, object],
    ) -> ApiResponse:
        return preview_tenant_memory_queue(
            database_path=self.database_path,
            tenant_id=tenant_id,
            payload=payload,
        )
