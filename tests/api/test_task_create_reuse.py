"""Reuse the committed cloud Task header; keep absent/local index preparation."""

from types import SimpleNamespace
from uuid import UUID

from agent_storage import PostgresControlPlaneStores
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.task_api import create_task

TASK = UUID("11111111-1111-4111-8111-111111111111")


def check_create_reuses_cloud_header():
    # No DB fixture: the native no-model/page probes verify actual commit/readback.
    from unittest.mock import Mock

    for cloud, present in ((True, True), (True, False), (False, True)):
        task = SimpleNamespace(task_id=TASK, active_segment_id=TASK, current_sequence=2)
        calls = []
        stores = Mock(spec=PostgresControlPlaneStores) if cloud else SimpleNamespace()
        stores.tasks = SimpleNamespace(
            get_task=lambda _, calls=calls, found=task if present else None: calls.append("get")
            or found,
            ensure_for_session=lambda _, calls=calls, task=task: calls.append("ensure") or task,
        )
        stores.sessions = SimpleNamespace(get_session=lambda _: SimpleNamespace(current_sequence=2))
        app = SimpleNamespace(
            stores=stores,
            create_session=lambda *a, **kw: ApiResponse(201, {"session_id": str(TASK)}),
        )
        result = create_task(app, {}, idempotency_key="fresh")
        assert result.status_code == 201
        assert result.body["task_id"] == str(TASK)
        assert calls == (
            ["get"] if cloud and present else ["get", "ensure"] if cloud else ["ensure"]
        )


def test_create_reuses_cloud_header():
    check_create_reuses_cloud_header()


if __name__ == "__main__":
    check_create_reuses_cloud_header()
    print("cloud header reuse and missing/local fallback pass")
