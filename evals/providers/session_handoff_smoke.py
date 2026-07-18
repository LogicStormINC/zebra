from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

from agent_storage import SQLiteEventStore
from zebra_agent_api import RouteAdapter, RouteRequest, create_app
from zebra_agent_config import load_settings


def main() -> int:
    settings = load_settings(
        {
            **os.environ,
            "ZEBRA_SESSION_HANDOFF_ENABLED": "true",
            "ZEBRA_RUNTIME_CLASS": "trusted-local",
        }
    )
    if not os.environ.get(settings.model.api_key_env, "").strip():
        print(json.dumps({"status": "skipped", "reason": "provider credential unavailable"}))
        return 2
    marker = f"ZEBRA-HANDOFF-{uuid4().hex[:12]}"
    with tempfile.TemporaryDirectory(prefix="zebra-handoff-smoke-") as temporary:
        root = Path(temporary)
        database = root / "sessions.db"
        app = create_app(database, settings=settings)
        parent = app.create_session(
            {
                "title": "Provider handoff parent",
                "prompt": f"Reply with exactly {marker}. Do not call tools.",
                "workspace": str(root),
                "execute": False,
                "tool_profile": "general",
            }
        )
        if parent.status_code != 201:
            return _fail("parent_create_failed", parent.body)
        parent_id = str(parent.body["session_id"])
        parent_run = app.resume_session(parent_id, {"worker_id": "provider-smoke-parent"})
        if parent_run.status_code != 200 or parent_run.body.get("status") != "completed":
            return _fail("parent_execution_failed", parent_run.body)
        handoff = RouteAdapter(app).handle(
            RouteRequest(
                method="POST",
                path=f"/sessions/{parent_id}/handoff",
                headers={"Idempotency-Key": f"provider-smoke-{marker}"},
                body={
                    "title": "Provider handoff child",
                    "objective": f"Preserve continuity marker {marker}",
                    "stage_prompt": (
                        "Read the handoff evidence and reply with its continuity marker exactly. "
                        "Do not call tools."
                    ),
                    "completed_work": ["parent provider call completed"],
                    "pending_work": ["prove child continuity"],
                },
            )
        )
        if handoff.status_code != 201:
            return _fail("handoff_create_failed", handoff.body)
        child_id = str(handoff.body["child_session_id"])
        child_run = app.resume_session(child_id, {"worker_id": "provider-smoke-child"})
        assistant = str(child_run.body.get("assistant_message", ""))
        child_events = SQLiteEventStore(database).list_for_session(_session_id(child_id))
        effect_starts = [
            event for event in child_events if event.event_type.value == "tool_execution_started"
        ]
        if child_run.status_code != 200 or child_run.body.get("status") != "completed":
            return _fail("child_execution_failed", child_run.body)
        if marker not in assistant:
            return _fail("continuity_marker_missing", {"assistant_length": len(assistant)})
        if effect_starts:
            return _fail("unexpected_child_side_effect", {"count": len(effect_starts)})
        print(
            json.dumps(
                {
                    "status": "passed",
                    "provider": settings.model.provider,
                    "model": settings.model.model,
                    "parent_session_hash": _hash(parent_id),
                    "child_session_hash": _hash(child_id),
                    "handoff_hash": _hash(str(handoff.body["handoff_id"])),
                    "continuity": True,
                    "duplicate_side_effects": 0,
                },
                sort_keys=True,
            )
        )
    return 0


def _session_id(value: str):
    from uuid import UUID

    from agent_core.domain.identifiers import SessionId

    return SessionId(UUID(value))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def _fail(reason: str, details: object) -> int:
    summary: dict[str, object] = {"status": "failed", "reason": reason}
    if isinstance(details, dict):
        for key in ("status", "error", "error_code", "reason"):
            if key in details:
                summary[f"provider_{key}"] = details[key]
    print(json.dumps(summary, default=str, sort_keys=True))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
