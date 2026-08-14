"""Approve the pending side-effect request and submit a resume command."""

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
    listing = adapter.handle(RouteRequest(method="GET", path="/approvals", headers={}, body=None))
    entries = listing.body.get("approvals", []) if isinstance(listing.body, dict) else []
    target = next(
        (
            entry
            for entry in entries
            if isinstance(entry, dict) and entry.get("session_id") == session_id
        ),
        None,
    )
    if target is None:
        print(json.dumps({"approved": False, "reason": "no_pending_approval"}))
        return 1
    approval_id = target.get("approval_id") or target.get("id")
    decision = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/approvals/{approval_id}/approve",
            headers={"Idempotency-Key": f"effect-e2e-approve-{approval_id}"},
            body={},
        )
    )
    events = api.stores.events.list_for_session(api._parse_session_id(session_id))
    revision = events[-1].sequence if events else 0
    resume = adapter.handle(
        RouteRequest(
            method="POST",
            path=f"/sessions/{session_id}/resume",
            headers={"Idempotency-Key": f"effect-e2e-resume-{revision}"},
            body={"expected_revision": revision},
        )
    )
    print(
        json.dumps(
            {
                "approved": decision.status_code in (200, 202),
                "resume_status": resume.status_code,
                "resume_body_status": (
                    resume.body.get("status") if isinstance(resume.body, dict) else None
                ),
                "revision": revision,
            }
        )
    )
    return 0 if decision.status_code in (200, 202) and resume.status_code == 202 else 1


if __name__ == "__main__":
    sys.exit(main())
