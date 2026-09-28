from datetime import UTC, datetime
from types import SimpleNamespace

from agent_core.domain.user_personalization import UserPersonalization
from agent_core.ports.user_personalization import UserPersonalizationConflictError
from zebra_agent_api.personalization_control import (
    clear_user_personalization,
    get_user_personalization,
    update_user_personalization,
)
from zebra_agent_api.personalization_routes import handle_personalization_route
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.routes import RouteRequest

NOW = datetime(2026, 9, 28, 6, 0, tzinfo=UTC)


class _Store:
    def __init__(self) -> None:
        self.record: UserPersonalization | None = None

    def get(self, user_id: str) -> UserPersonalization | None:
        return self.record if self.record is not None and self.record.user_id == user_id else None

    def put(
        self,
        user_id: str,
        instructions: str,
        *,
        expected_revision: int,
        operator: str,
    ) -> UserPersonalization:
        current = 0 if self.record is None else self.record.revision
        if current != expected_revision:
            raise UserPersonalizationConflictError("personalization revision changed")
        self.record = UserPersonalization(
            user_id=user_id,
            instructions=instructions,
            revision=current + 1,
            updated_at=NOW,
            operator=operator,
        )
        return self.record

    def clear(
        self, user_id: str, *, expected_revision: int, operator: str
    ) -> UserPersonalization:
        current = 0 if self.record is None else self.record.revision
        if current != expected_revision:
            raise UserPersonalizationConflictError("personalization revision changed")
        self.record = UserPersonalization(
            user_id=user_id,
            instructions=None,
            revision=current + 1,
            updated_at=NOW,
            operator=operator,
        )
        return self.record


def test_personalization_create_read_and_clear_use_revision_cas() -> None:
    store = _Store()
    stores = SimpleNamespace(personalization=store)

    assert get_user_personalization(stores=stores, user_id="user-1").body == {
        "instructions": "",
        "revision": 0,
        "updated_at": None,
    }
    saved = update_user_personalization(
        stores=stores,
        user_id="user-1",
        payload={
            "instructions": "  Prefer concise answers.  ",
            "expected_revision": 0,
            "operator": "user-1",
        },
    )
    assert saved.status_code == 200
    assert saved.body["instructions"] == "Prefer concise answers."
    assert saved.body["revision"] == 1

    stale = update_user_personalization(
        stores=stores,
        user_id="user-1",
        payload={
            "instructions": "Use tables.",
            "expected_revision": 0,
            "operator": "user-1",
        },
    )
    assert stale.status_code == 409

    cleared = clear_user_personalization(
        stores=stores,
        user_id="user-1",
        payload={"expected_revision": 1, "operator": "user-1"},
    )
    assert cleared.body["instructions"] == ""
    assert cleared.body["revision"] == 2


def test_personalization_route_dispatches_without_colliding_with_memory() -> None:
    response = handle_personalization_route(
        SimpleNamespace(
            update_user_personalization=lambda user_id, payload: ApiResponse(
                200, {"user_id": user_id, **payload}
            )
        ),
        RouteRequest(
            method="PUT",
            path="/users/user-1/personalization",
            body={"instructions": "Use evidence."},
        ),
    )

    assert response == ApiResponse(
        200, {"user_id": "user-1", "instructions": "Use evidence."}
    )
    assert (
        handle_personalization_route(
            SimpleNamespace(),
            RouteRequest(method="GET", path="/users/user-1/memory"),
        )
        is None
    )
