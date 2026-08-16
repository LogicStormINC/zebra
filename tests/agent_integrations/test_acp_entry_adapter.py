"""ARCH-129-ACP-01: ACP entry adapter over the durable command lane."""

from __future__ import annotations

from pathlib import Path

import pytest
from agent_integrations.acp import AcpAdapterError, AcpEntryAdapter
from agent_storage import sqlite_control_plane_stores
from zebra_agent_api import create_app


def _app(tmp_path: Path) -> object:
    stores = sqlite_control_plane_stores(tmp_path / "control.sqlite")
    from zebra_agent_config import load_settings

    return create_app(
        str(tmp_path / "api.sqlite"),
        settings=load_settings(env={"ZEBRA_PROFILE": "local"}),
        stores=stores,
    )


def _initialize(adapter: AcpEntryAdapter) -> tuple[object, object]:
    handle, response = adapter.initialize_session(
        {"prompt": "acp entry probe", "execute": False},
        idempotency_key="acp-init-1",
    )
    assert response.status_code == 201
    return handle, response


def test_initialize_maps_onto_durable_session(tmp_path: Path) -> None:
    app = _app(tmp_path)
    adapter = AcpEntryAdapter(app)
    handle, response = _initialize(adapter)
    assert handle.acp_session_ref.startswith("acp:")
    assert handle.session_id in response.body["session_id"]
    stored = app.stores.sessions.get_session(handle.session_id)
    assert stored is not None


def test_reconnect_resumes_from_durable_checkpoint(tmp_path: Path) -> None:
    app = _app(tmp_path)
    adapter = AcpEntryAdapter(app)
    handle, _response = _initialize(adapter)
    events = adapter.events_after(handle)
    assert len(events) >= 2
    resumed = adapter.resume_session(
        handle.acp_session_ref,
        last_delivered_sequence=events[0].sequence,
    )
    tail = adapter.events_after(resumed)
    assert [event.sequence for event in tail] == [
        event.sequence for event in events[1:]
    ]
    # a fresh reconnect at the same checkpoint replays identically
    again = adapter.events_after(
        adapter.resume_session(
            handle.acp_session_ref,
            last_delivered_sequence=events[0].sequence,
        )
    )
    assert [event.sequence for event in again] == [event.sequence for event in tail]


def test_invalid_refs_fail_closed(tmp_path: Path) -> None:
    app = _app(tmp_path)
    adapter = AcpEntryAdapter(app)
    with pytest.raises(AcpAdapterError):
        adapter.resume_session("not-acp:1234", last_delivered_sequence=0)
    with pytest.raises(AcpAdapterError):
        adapter.resume_session("acp:not-a-uuid", last_delivered_sequence=0)


def test_cancel_routes_through_the_command_lane(tmp_path: Path) -> None:
    app = _app(tmp_path)
    adapter = AcpEntryAdapter(app)
    handle, _response = _initialize(adapter)
    response = adapter.cancel(handle.acp_session_ref)
    assert response.status_code in (200, 404, 409)
