from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
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
    "finos.positions.list",
    "finos.notes.list",
    "finos.notes.get",
    "finos.securities.resolve",
]
FINOS_V2_TOOLS = [*FINOS_TOOLS, "finos.account_changes.propose", "finos.journals.save"]
FINOS_V3_TOOLS = [*FINOS_V2_TOOLS, "finos.trade_log_quality.validate"]
FINOS_V4_TOOLS = [
    *FINOS_V3_TOOLS,
    "finos.investor_knowledge.list",
    "finos.investor_knowledge.get",
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


def test_task_finos_provider_binding_accepts_v2_with_only_the_proposal_addition(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    created = adapter.handle(
        RouteRequest("POST", "/tasks", body={"prompt": "Review", "workspace": str(tmp_path)})
    )
    task_id = created.body["task_id"]

    bound = adapter.handle(
        RouteRequest(
            "PUT",
            f"/tasks/{task_id}/business-providers/finos-journals",
            body=_binding("private-v2-grant", contract_version="finos.journals.v2"),
        )
    )

    assert bound.status_code == 200
    assert bound.body == {
        "task_id": task_id,
        "business_tools": {"contract_version": "finos.journals.v2", "names": FINOS_V2_TOOLS},
    }
    assert "private-v2-grant" not in str(bound.body)


def test_task_finos_provider_binding_accepts_v3_with_the_validator_addition(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    created = adapter.handle(
        RouteRequest("POST", "/tasks", body={"prompt": "Review", "workspace": str(tmp_path)})
    )
    task_id = created.body["task_id"]

    bound = adapter.handle(
        RouteRequest(
            "PUT",
            f"/tasks/{task_id}/business-providers/finos-journals",
            body=_binding("private-v3-grant", contract_version="finos.journals.v3"),
        )
    )

    assert bound.status_code == 200
    assert bound.body == {
        "task_id": task_id,
        "business_tools": {"contract_version": "finos.journals.v3", "names": FINOS_V3_TOOLS},
    }
    assert "private-v3-grant" not in str(bound.body)


def test_task_finos_provider_binding_accepts_v4_with_only_knowledge_reads(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    created = adapter.handle(
        RouteRequest("POST", "/tasks", body={"prompt": "Review", "workspace": str(tmp_path)})
    )
    task_id = created.body["task_id"]

    bound = adapter.handle(
        RouteRequest(
            "PUT",
            f"/tasks/{task_id}/business-providers/finos-journals",
            body=_binding("private-v4-grant", contract_version="finos.journals.v4"),
        )
    )

    assert bound.status_code == 200
    assert bound.body == {
        "task_id": task_id,
        "business_tools": {
            "contract_version": "finos.journals.v4",
            "names": FINOS_V4_TOOLS,
        },
    }
    assert "private-v4-grant" not in str(bound.body)


def test_task_finos_provider_binding_persists_model_tool_selection_across_rotation(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    created = adapter.handle(
        RouteRequest("POST", "/tasks", body={"prompt": "Review", "workspace": str(tmp_path)})
    )
    task_id = created.body["task_id"]
    path = f"/tasks/{task_id}/business-providers/finos-journals"
    expiry = datetime.now(UTC) + timedelta(minutes=10)
    selected = ["finos.trade_log_quality.validate", "finos.journals.list"]

    bound = adapter.handle(
        RouteRequest(
            "PUT",
            path,
            body=_binding(
                "first-private-grant",
                expiry,
                contract_version="finos.journals.v3",
                model_tool_names=selected,
            ),
        )
    )
    rotated = adapter.handle(
        RouteRequest(
            "PUT",
            path,
            body=_binding(
                "rotated-private-grant",
                expiry + timedelta(minutes=1),
                contract_version="finos.journals.v3",
            ),
        )
    )
    changed = adapter.handle(
        RouteRequest(
            "PUT",
            path,
            body=_binding(
                "changed-private-grant",
                expiry + timedelta(minutes=2),
                contract_version="finos.journals.v3",
                model_tool_names=["finos.journals.get"],
            ),
        )
    )

    expected = ["finos.journals.list", "finos.trade_log_quality.validate"]
    assert bound.status_code == 200
    assert bound.body["business_tools"]["names"] == expected
    assert rotated.status_code == 200
    assert rotated.body["business_tools"]["names"] == expected
    assert changed.status_code == 409
    assert "first-private-grant" not in str(bound.body)
    assert "rotated-private-grant" not in str(rotated.body)


@pytest.mark.parametrize(
    "model_tool_names",
    (
        [],
        [""],
        ["finos.journals.list", "finos.journals.list"],
        ["finos.unknown"],
        ["finos.journals.list", 1],
        "finos.journals.list",
        None,
    ),
)
def test_task_finos_provider_rejects_invalid_model_tool_selection(
    tmp_path: Path,
    model_tool_names: object,
) -> None:
    adapter = _adapter(tmp_path)
    created = adapter.handle(
        RouteRequest("POST", "/tasks", body={"prompt": "Review", "workspace": str(tmp_path)})
    )

    response = adapter.handle(
        RouteRequest(
            "PUT",
            f"/tasks/{created.body['task_id']}/business-providers/finos-journals",
            body=_binding("private", model_tool_names=model_tool_names),
        )
    )

    assert response.status_code == 400


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
    *,
    contract_version: str = "finos.journals.v1",
    model_tool_names: object = ...,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "contract_version": contract_version,
        "grant": grant,
        "expires_at": (expires_at or datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    }
    if model_tool_names is not ...:
        payload["model_tool_names"] = model_tool_names
    return payload


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
