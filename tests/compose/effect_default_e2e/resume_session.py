"""Submit one explicit durable resume command for recovery scenarios."""

from __future__ import annotations

import json
import os
import sys

from zebra_agent_api import create_app
from zebra_agent_api.routes import RouteAdapter, RouteRequest
from zebra_agent_config import load_settings


def main() -> int:
    session_id = os.environ["ZEBRA_EFFECT_E2E_SESSION_ID"]
    api = create_app(settings=load_settings())
    events = api.stores.events.list_for_session(api._parse_session_id(session_id))
    revision = events[-1].sequence if events else 0
    response = RouteAdapter(api).handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/resume",
            headers={"Idempotency-Key": f"effect-e2e-resume-{revision}"},
            body={"expected_revision": revision},
        )
    )
    print(json.dumps({"status": response.status_code, "revision": revision}))
    return 0 if response.status_code == 202 else 1


if __name__ == "__main__":
    sys.exit(main())
