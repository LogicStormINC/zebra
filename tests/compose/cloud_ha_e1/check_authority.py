"""Runnable no-network check for fixed fixture identity, scope and body limits."""

import json
import os
import runpy
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

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
    finally:
        if previous is None:
            os.environ.pop("E1_PRINCIPALS_FILE")
        else:
            os.environ["E1_PRINCIPALS_FILE"] = previous
print("Fixed E1 identity, denied permissions and body bounds passed.")
