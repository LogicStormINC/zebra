"""Seed one queued session through the committed API application object."""

from __future__ import annotations

import json
import os
import sys

from zebra_agent_api import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest
from zebra_agent_config import load_settings


def main() -> int:
    workspace = os.environ.get("ZEBRA_EFFECT_E2E_WORKSPACE", "")
    source_json = os.environ.get("ZEBRA_EFFECT_E2E_WORKSPACE_SOURCE")
    settings = load_settings()
    api = create_app(settings=settings)
    adapter = RouteAdapter(api)
    response = adapter.handle(
        RouteRequest(
            method="POST",
            path="/sessions",
            headers={"Idempotency-Key": os.environ["ZEBRA_EFFECT_E2E_SEED_KEY"]},
            body={
                "prompt": os.environ["ZEBRA_EFFECT_E2E_PROMPT"],
                "title": "effect default e2e",
                **({} if source_json else {"workspace": workspace}),
                "execute": False,
                "policy_profile": "workspace_write",
                "tool_profile": "general",
                **({"workspace_source": json.loads(source_json)} if source_json else {}),
            },
        )
    )
    body = response.body if isinstance(response.body, dict) else {}
    print(
        json.dumps(
            {
                "status": response.status_code,
                "session_id": body.get("session_id"),
                "workspace": workspace,
            }
        )
    )
    return 0 if response.status_code == 201 else 1


if __name__ == "__main__":
    sys.exit(main())
