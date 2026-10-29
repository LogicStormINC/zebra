from dataclasses import fields
from pathlib import Path
from uuid import UUID

import pytest
from agent_core.domain.identifiers import SessionId, new_artifact_id
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
        "artifact_payload_reader",
        "projection_work",
        "coverage_projection_work",
        "projection_work_for_version",
    }
    assert stores.projection_work is not None
    assert stores.projection_work.read_pending_projection_work(limit=1) == ()
    assert stores.coverage_projection_work is not None
    assert stores.coverage_projection_work is not stores.projection_work
    assert stores.coverage_projection_work.read_pending_projection_work(limit=1) == ()
    assert stores.projection_work_for_version is not None
    selected = stores.projection_work_for_version("agui-standard-1.0:r1")
    assert selected is not stores.projection_work
    assert selected.read_pending_projection_work(limit=1) == ()
    # Discovery/read factory never enables a writer or registers a profile version.
    import sqlite3

    with sqlite3.connect(tmp_path / "authority.sqlite") as connection:
        assert (
            connection.execute(
                "SELECT projector_version FROM task_projection_work_projectors "
                "ORDER BY projector_version"
            ).fetchall()
            == []
        )
    session_id = SessionId(UUID("00000000-0000-0000-0000-000000000001"))
    assert stores.artifacts.list_for_session(session_id) == []
    assert stores.artifact_payload_reader is not None
    assert (
        stores.artifact_payload_reader.inspect_payload(
            session_id,
            f"artifact://{new_artifact_id()}",
        )
        is None
    )
    assert stores.session_history.scoped(None) is not stores.session_history
