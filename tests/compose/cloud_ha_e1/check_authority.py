"""Runnable no-network check for fixed fixture identity, scope and body limits."""

import json
import os
import runpy
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from zebra_host_grant_broker.app import create_app
from zebra_host_grant_broker.current_authority import fetch_authority

from tests.host_grant_broker.test_current_authority import _headers
from tests.host_grant_broker.test_grant_broker import _key, _settings, _verify_with_zebra

with tempfile.TemporaryDirectory() as temporary:
    path = Path(temporary) / "principals.json"
    path.write_text(
        json.dumps(
            [
                dict(
                    principal=f"principal-{i}",
                    workspace=f"workspace-{i}",
                    token=f"fixture-token-{i}",
                )
                for i in range(32)
            ]
        )
    )
    previous = os.environ.get("E1_PRINCIPALS_FILE")
    os.environ["E1_PRINCIPALS_FILE"] = str(path)
    try:
        with patch.dict(os.environ, {"E1_SCHEDULER_SHARED_SECRET": "scheduler-secret"}):
            app = runpy.run_path(str(Path(__file__).with_name("authority.py")))["app"]
        with TestClient(app) as client:
            headers = {"Authorization": "Bearer fixture-token-4"}
            body = dict(audience="zebra", threadId="thread", runId="run", scopes=["agent.run"])
            result = client.post("/authority", headers=headers, json=body)
            assert result.status_code == 200
            assert result.json()["principalId"] == "principal-4"
            assert result.json()["workspaceId"] == "workspace-4"
            assert client.post("/authority", json=body).status_code == 403
            assert (
                client.post(
                    "/authority", headers=headers, json=body | {"scopes": ["schedule.manage"]}
                ).status_code
                == 403
            )
            assert (
                client.post(
                    "/authority",
                    headers=headers,
                    json=body | {"resourceRefs": [{"type": "artifact", "id": "foreign"}]},
                ).status_code
                == 403
            )
            assert (
                client.post("/authority", headers=headers, content="x" * 65537).status_code == 413
            )
            management = body | {"scopes": ["schedule.manage"]}
            owner = {"Authorization": "Bearer fixture-token-0"}
            assert client.post("/authority", headers=owner, json=management).status_code == 200
            key = _key()
            settings = replace(
                _settings(key),
                authority_mode="generic",
                host_app_id="ha-e1",
                namespace_id="ha-e1-20261102",
                authority_url="https://e1.invalid/authority",
                workload_identities=("e1-scheduler",),
                workload_shared_secret="scheduler-secret",
                allowed_scopes=("agent.run", "event.read", "schedule.manage"),
            )
            transport = httpx.MockTransport(
                lambda request: client.post(
                    "/authority", content=request.content, headers=request.headers
                )
            )
            with (
                patch(
                    "zebra_host_grant_broker.app.fetch_authority",
                    lambda *args, **kwargs: fetch_authority(*args, **kwargs, transport=transport),
                ),
                TestClient(create_app(settings)) as broker,
            ):
                for principal, scopes, status in (
                    ("principal-0", ["agent.run", "event.read"], 200),
                    ("principal-4", ["agent.run"], 401),
                    ("principal-0", ["schedule.manage"], 401),
                ):
                    payload = body | {
                        "principal": {"userId": principal, "workspaceId": "workspace-0"},
                        "scopes": scopes,
                    }
                    workload = _headers(payload) | {"X-Zebra-Workload-Identity": "e1-scheduler"}
                    response = broker.post("/exchange", headers=workload, json=payload)
                    assert response.status_code == status, response.json().get("reason")
                    if status == 200:
                        verified = _verify_with_zebra(response.json()["grant"], settings, key)
                        assert set(verified.context.scopes) == {"agent.run", "event.read"}
                        assert {ref.key for ref in verified.context.resource_refs} == {
                            ("principal", principal),
                            ("thread", "thread"),
                            ("run", "run"),
                        }
                        assert (
                            broker.post(
                                "/exchange", headers=workload, json=payload | {"runId": "tampered"}
                            ).status_code
                            == 401
                        )
    finally:
        if previous is None:
            os.environ.pop("E1_PRINCIPALS_FILE")
        else:
            os.environ["E1_PRINCIPALS_FILE"] = previous
print("Fixed E1 identity, denied permissions and body bounds passed.")
