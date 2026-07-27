from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from zebra_agent_api import RouteAdapter, RouteRequest, create_app, create_http_app
from zebra_agent_config import (
    ApiSettings,
    FinosJournalProviderSettings,
    ModelSettings,
    ZebraAgentSettings,
)

FINOS_TOOLS = [
    "finos.journals.list",
    "finos.journals.get",
    "finos.snapshots.list",
    "finos.snapshots.get",
    "finos.transactions.list",
    "finos.notes.list",
    "finos.notes.get",
    "finos.securities.resolve",
]


def test_task_finos_provider_binding_is_private_and_advertises_fixed_catalog(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    created = adapter.handle(
        RouteRequest(
            "POST",
            "/tasks",
            body={"prompt": "Review journals", "workspace": str(tmp_path)},
        )
    )
    task_id = created.body["task_id"]
    grant = "private-task-grant"

    bound = adapter.handle(
        RouteRequest(
            "PUT",
            f"/tasks/{task_id}/business-providers/finos-journals",
            body=_binding(grant),
        )
    )
    missing = adapter.handle(
        RouteRequest("PUT", f"/tasks/{task_id}/business-providers/finos-journals", body={})
    )
    public_task = adapter.handle(RouteRequest("GET", f"/tasks/{task_id}"))
    public_stream = adapter.handle(RouteRequest("GET", f"/tasks/{task_id}/stream"))

    assert bound.status_code == 200
    assert missing.status_code == 400
    assert bound.body == {
        "task_id": task_id,
        "business_tools": {"contract_version": "finos.journals.v1", "names": FINOS_TOOLS},
    }
    assert grant not in str(bound.body)
    assert grant not in str(public_task.body)
    assert grant not in str(public_stream.body)


def test_task_finos_provider_rejects_when_endpoint_is_not_configured(tmp_path: Path) -> None:
    client = TestClient(
        create_http_app(settings=_settings(tmp_path / "tasks.sqlite", base_url=None))
    )
    created = client.post(
        "/tasks",
        json={"prompt": "Review", "workspace": str(tmp_path)},
    )

    bound = client.put(
        f"/tasks/{created.json()['task_id']}/business-providers/finos-journals",
        json=_binding("private"),
    )

    assert bound.status_code == 503
    assert bound.json()["status"] == "provider_unavailable"


def test_task_finos_provider_rejects_unknown_fields_and_stale_rotation(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    created = adapter.handle(
        RouteRequest("POST", "/tasks", body={"prompt": "Review", "workspace": str(tmp_path)})
    )
    path = f"/tasks/{created.body['task_id']}/business-providers/finos-journals"
    expires_at = datetime.now(UTC) + timedelta(minutes=10)

    unknown = adapter.handle(
        RouteRequest("PUT", path, body={**_binding("first", expires_at), "tools": FINOS_TOOLS})
    )
    arbitrary_url = adapter.handle(
        RouteRequest(
            "PUT",
            path,
            body={**_binding("first", expires_at), "url": "https://untrusted.example"},
        )
    )
    first = adapter.handle(RouteRequest("PUT", path, body=_binding("first", expires_at)))
    renewed = adapter.handle(RouteRequest("PUT", path, body=_binding("renewed", expires_at)))
    replayed = adapter.handle(RouteRequest("PUT", path, body=_binding("first", expires_at)))
    expired = adapter.handle(
        RouteRequest(
            "PUT",
            path,
            body=_binding("expired", datetime.now(UTC) - timedelta(seconds=1)),
        )
    )
    stale = adapter.handle(
        RouteRequest("PUT", path, body=_binding("stale", expires_at - timedelta(seconds=1)))
    )
    rotated = adapter.handle(
        RouteRequest("PUT", path, body=_binding("rotated", expires_at + timedelta(minutes=1)))
    )

    assert unknown.status_code == 400
    assert arbitrary_url.status_code == 400
    assert first.status_code == 200
    assert renewed.status_code == 200
    assert replayed.status_code == 409
    assert expired.status_code == 400
    assert stale.status_code == 409
    assert rotated.status_code == 200
    assert "rotated" not in str(rotated.body)


def test_task_finos_provider_rejects_a_grant_already_bound_to_another_task(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    first = adapter.handle(
        RouteRequest("POST", "/tasks", body={"prompt": "First", "workspace": str(tmp_path)})
    )
    second = adapter.handle(
        RouteRequest("POST", "/tasks", body={"prompt": "Second", "workspace": str(tmp_path)})
    )
    grant = _binding("private-task-grant")

    bound = adapter.handle(
        RouteRequest(
            "PUT",
            f"/tasks/{first.body['task_id']}/business-providers/finos-journals",
            body=grant,
        )
    )
    crossed = adapter.handle(
        RouteRequest(
            "PUT",
            f"/tasks/{second.body['task_id']}/business-providers/finos-journals",
            body=grant,
        )
    )

    assert bound.status_code == 200
    assert crossed.status_code == 409


def test_task_finos_provider_uses_normal_api_authentication(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "tasks.sqlite", auth_token="zebra-secret")
    client = TestClient(create_http_app(settings=settings))
    headers = {"Authorization": "Bearer zebra-secret"}
    created = client.post(
        "/tasks",
        headers=headers,
        json={"prompt": "Review", "workspace": str(tmp_path)},
    )
    path = f"/tasks/{created.json()['task_id']}/business-providers/finos-journals"

    unauthorized = client.put(path, json=_binding("private"))
    authorized = client.put(path, headers=headers, json=_binding("private"))

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert "private" not in authorized.text


def test_task_finos_provider_binding_survives_same_task_continuation(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    created = adapter.handle(
        RouteRequest("POST", "/tasks", body={"prompt": "Review", "workspace": str(tmp_path)})
    )
    task_id = created.body["task_id"]
    path = f"/tasks/{task_id}/business-providers/finos-journals"
    expiry = datetime.now(UTC) + timedelta(minutes=10)
    bound = adapter.handle(RouteRequest("PUT", path, body=_binding("private", expiry)))
    cancelled = adapter.handle(RouteRequest("POST", f"/tasks/{task_id}/cancel", body={}))
    assert bound.status_code == 200
    assert cancelled.status_code == 200

    continued = adapter.handle(
        RouteRequest("POST", f"/tasks/{task_id}/messages", body={"content": "Continue"})
    )
    stale = adapter.handle(
        RouteRequest("PUT", path, body=_binding("stale", expiry - timedelta(seconds=1)))
    )

    assert continued.status_code == 201
    assert continued.body["task_id"] == task_id
    assert continued.body["session_id"] == task_id
    assert stale.status_code == 409


def _binding(
    grant: str,
    expires_at: datetime | None = None,
) -> dict[str, str]:
    return {
        "contract_version": "finos.journals.v1",
        "grant": grant,
        "expires_at": (expires_at or datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    }


def _adapter(tmp_path: Path, *, base_url: str | None = "https://finos.internal") -> RouteAdapter:
    database = tmp_path / "tasks.sqlite"
    return RouteAdapter(create_app(database, settings=_settings(database, base_url=base_url)))


def _settings(
    database: Path,
    *,
    base_url: str | None = "https://finos.internal",
    auth_token: str | None = None,
) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=str(database),
        api=ApiSettings(auth_token=auth_token),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
        finos_journal_provider=FinosJournalProviderSettings(base_url=base_url),
    )
