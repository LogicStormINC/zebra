from dataclasses import fields
from pathlib import Path
from uuid import UUID

import pytest
from agent_core.domain.identifiers import SessionId
from agent_storage import sqlite_control_plane_stores


def test_sqlite_control_plane_stores_require_filesystem_database() -> None:
    with pytest.raises(ValueError, match="filesystem-backed database"):
        sqlite_control_plane_stores(":memory:")


def test_sqlite_control_plane_stores_compose_every_authoritative_boundary(
    tmp_path: Path,
) -> None:
    stores = sqlite_control_plane_stores(tmp_path / "authority.sqlite")

    assert {field.name for field in fields(stores)} == {
        "events",
        "sessions",
        "workspaces",
        "tasks",
        "leases",
        "context_lifecycle",
        "handoffs",
        "handoff_dispatch",
        "idempotency",
        "effects",
        "memories",
        "artifact_payloads",
        "model_calls",
        "tool_runs",
        "artifacts",
        "provider_continuations",
        "session_history",
        "delivery_audit",
    }
    session_id = SessionId(UUID("00000000-0000-0000-0000-000000000001"))
    assert stores.artifacts.list_for_session(session_id) == []
    assert stores.session_history.scoped(None) is not stores.session_history
