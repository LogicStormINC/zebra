"""Approve the pending side-effect request; approval submits its durable resume."""

from __future__ import annotations

import json
import os
import sys

from zebra_agent_api import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest
from zebra_agent_config import load_settings


def main() -> int:
    session_id = os.environ["ZEBRA_EFFECT_E2E_SESSION_ID"]
    settings = load_settings()
    api = create_app(settings=settings)
    adapter = RouteAdapter(api)
    decision = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/approvals/{session_id}/approve",
            headers={"Idempotency-Key": f"effect-e2e-approve-{session_id}"},
            body={},
        )
    )
    approved = (
        decision.status_code == 200
        and isinstance(decision.body, dict)
        and decision.body.get("event_type") == "approval_granted"
    )
    print(
        json.dumps(
            {
                "approved": approved,
                "approval_status": decision.status_code,
                "session_status": (
                    decision.body.get("status")
                    if isinstance(decision.body, dict)
                    else None
                ),
            }
        )
    )
    return 0 if approved else 1


if __name__ == "__main__":
    sys.exit(main())
