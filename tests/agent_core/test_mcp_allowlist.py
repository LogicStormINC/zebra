from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.mcp import normalize_mcp_allowlist


def test_mcp_allowlist_is_canonical_unique_bounded_and_sorted() -> None:
    assert normalize_mcp_allowlist(("mcp.zeta.read", "mcp.alpha.write")) == (
        "mcp.alpha.write",
        "mcp.zeta.read",
    )
    with pytest.raises(ValueError, match="canonical"):
        normalize_mcp_allowlist(("mcp.alpha.*",))
    with pytest.raises(ValueError, match="unique"):
        normalize_mcp_allowlist(("mcp.alpha.read", "mcp.alpha.read"))
    with pytest.raises(ValueError, match="at most 32"):
        normalize_mcp_allowlist(tuple(f"mcp.server.tool{index}" for index in range(33)))


def test_new_bootstrap_records_explicit_empty_allowlist() -> None:
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Default deny",
            user_input="Do not use MCP.",
            workspace_root=Path("/tmp/default-deny"),
        )
    )

    prepared = next(
        event for event in bootstrap.events if event.event_type is EventType.TASK_PREPARED
    )
    assert prepared.payload["mcp_allowlist"] == []
    assert rebuild_workspace(list(bootstrap.events)).mcp_allowlist == ()


def test_legacy_task_without_allowlist_remains_distinguishable() -> None:
    event = SessionEvent.create(
        session_id="00000000-0000-0000-0000-000000000001",
        sequence=0,
        event_type=EventType.TASK_PREPARED,
        actor=EventActor.HARNESS,
        payload={
            "title": "Legacy",
            "user_input": "Continue",
            "workspace_root": "/tmp/legacy-mcp",
        },
        created_at=datetime(2026, 7, 16, tzinfo=UTC),
    )

    assert "mcp_allowlist" not in event.payload
    assert rebuild_workspace([event]).mcp_allowlist is None
