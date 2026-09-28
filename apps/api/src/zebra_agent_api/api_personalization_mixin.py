from __future__ import annotations

from agent_storage import ControlPlaneStores

from zebra_agent_api.personalization_control import (
    clear_user_personalization,
    get_user_personalization,
    update_user_personalization,
)
from zebra_agent_api.responses import ApiResponse


class ApiPersonalizationMixin:
    stores: ControlPlaneStores

    def get_user_personalization(self, user_id: str) -> ApiResponse:
        return get_user_personalization(stores=self.stores, user_id=user_id)

    def update_user_personalization(
        self, user_id: str, payload: dict[str, object]
    ) -> ApiResponse:
        return update_user_personalization(
            stores=self.stores, user_id=user_id, payload=payload
        )

    def clear_user_personalization(
        self, user_id: str, payload: dict[str, object]
    ) -> ApiResponse:
        return clear_user_personalization(
            stores=self.stores, user_id=user_id, payload=payload
        )
