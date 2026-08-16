"""Create or read one Workspace Control Plane record through the API app."""

from __future__ import annotations

import json
import os
import sys

from zebra_agent_api import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest
from zebra_agent_config import load_settings


def main() -> int:
    settings = load_settings()
    api = create_app(settings=settings)
    adapter = RouteAdapter(api)
    workspace_id = os.environ.get("ZEBRA_EFFECT_E2E_WORKSPACE_ID")
    if workspace_id:
        response = adapter.handle(
            RouteRequest(method="GET", path=f"/workspaces/{workspace_id}", headers={}, body=None)
        )
        print(
            json.dumps(
                {
                    "status": response.status_code,
                    "workspace_id": workspace_id,
                    **({"workspace": response.body} if isinstance(response.body, dict) else {}),
                }
            )
        )
        return 0 if response.status_code == 200 else 1
    source_payload = {
        "kind": "git_repository",
        "locator": os.environ["ZEBRA_EFFECT_E2E_SOURCE_REPO"],
        "pinned_revision": os.environ["ZEBRA_EFFECT_E2E_SOURCE_REVISION"],
    }
    response = adapter.handle(
        RouteRequest(
            method="POST",
            path="/workspaces",
            headers={},
            body={
                "source": source_payload,
                "quota_bytes": 256 * 1024 * 1024,
                "idempotency_key": os.environ.get(
                    "ZEBRA_EFFECT_E2E_WORKSPACE_KEY", "cp-workspace-1"
                ),
            },
        )
    )
    print(
        json.dumps(
            {
                "status": response.status_code,
                "workspace_id": response.body.get("workspace_id")
                if isinstance(response.body, dict)
                else None,
                "source_payload": source_payload,
            }
        )
    )
    return 0 if response.status_code == 201 else 1


if __name__ == "__main__":
    sys.exit(main())
