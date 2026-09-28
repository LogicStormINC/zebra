from typing import Protocol

from agent_core.domain.user_personalization import UserPersonalization


class UserPersonalizationConflictError(RuntimeError):
    pass


class UserPersonalizationStorePort(Protocol):
    def get(self, user_id: str) -> UserPersonalization | None: ...

    def put(
        self,
        user_id: str,
        instructions: str,
        *,
        expected_revision: int,
        operator: str,
    ) -> UserPersonalization: ...

    def clear(
        self,
        user_id: str,
        *,
        expected_revision: int,
        operator: str,
    ) -> UserPersonalization: ...
