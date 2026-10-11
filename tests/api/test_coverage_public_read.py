"""Persisted strict admission guards raw replay, downloads and range aliases."""

import asyncio
from pathlib import Path

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.agent_tasks import RolloverReason
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import TaskId
from agent_storage import sqlite_control_plane_stores
from starlette.requests import Request
from zebra_agent_api.artifact_download import artifact_download_response
from zebra_agent_api.session_read import SessionReadApi
from zebra_agent_api.session_streaming import tail_session_events, tail_task_events
from zebra_agent_api.task_api import TaskReadApi, route_active_task


def seed(path: Path, raw):
    stores = sqlite_control_plane_stores(path)
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Strict output",
            user_input="review",
            workspace_root=path.parent,
        )
    )
    for row in bootstrap.events:
        if row.event_type is EventType.TASK_PREPARED:
            row = row.model_copy(update={"payload": row.payload | {"coverage_admission": raw}})
        stores.events.append(row)
    stores.sessions.save_session(bootstrap.session)
    stores.tasks.ensure_for_session(bootstrap.session.session_id)
    return stores, bootstrap.session.session_id


@pytest.mark.parametrize("raw", [None, {}, "invalid"])
def test_raw_replay_and_all_artifact_entrypoints_refuse_before_payload_io(tmp_path, raw):
    path = tmp_path / "events.sqlite"
    stores, sid = seed(path, raw)
    api = SessionReadApi(path, stores)
    responses = (
        api.get_session_stream(str(sid)),
        TaskReadApi(stores).stream(str(sid)),
        api.get_session_artifacts(str(sid)),
        api.get_session_artifact_detail(str(sid), "candidate"),
        api.get_session_artifact_content(str(sid), "candidate"),
        api.get_session_artifact_content(str(sid), "candidate", byte_range=(0, 1)),
    )
    assert all(item.status_code == 409 for item in responses)
    assert all(item.body["status"] == "coverage_report_required" for item in responses)

    class Connected:
        async def is_disconnected(self):
            raise AssertionError("strict guard must precede raw tail/cursor/fanout")

    async def replay():
        for generator in (
            tail_session_events(
                database_path=path,
                stores=stores,
                session_id=sid,
                request=Connected(),
                after_sequence=999,
            ),
            tail_task_events(
                database_path=path,
                stores=stores,
                task_id=TaskId(sid),
                request=Connected(),
                after_sequence=999,
            ),
        ):
            assert [item async for item in generator] == []

    asyncio.run(replay())


@pytest.mark.parametrize("public_id", ["candidate", "tool:candidate"])
@pytest.mark.parametrize(
    ("method", "suffix"), [("GET", "download"), ("GET", "preview"), ("HEAD", "preview")]
)
def test_download_alias_head_and_range_cannot_bypass_guard(tmp_path, method, public_id, suffix):
    path = tmp_path / "events.sqlite"
    stores, sid = seed(path, None)
    api = SessionReadApi(path, stores)

    class Adapter:
        def handle(self, route):
            if route.path.endswith("/artifacts"):
                return api.get_session_artifacts(str(sid))
            return api.get_session_artifact_detail(str(sid), public_id)

    request = Request(
        {
            "type": "http",
            "method": method,
            "scheme": "http",
            "server": ("test", 80),
            "path": f"/tasks/{sid}/artifacts/{public_id}/{suffix}",
            "query_string": b"",
            "headers": [(b"range", b"bytes=0-1")],
        }
    )
    response = asyncio.run(artifact_download_response(request, Adapter()))
    assert response is not None and response.status_code == 409
    assert b"coverage_report_required" in response.body


def test_child_segment_inherits_parent_strict_identity_for_raw_and_artifact_aliases(tmp_path):
    path = tmp_path / "child.sqlite"
    stores, parent = seed(path, None)
    child = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Continuation",
            user_input="continue",
            workspace_root=tmp_path,
        )
    )
    for row in child.events:
        stores.events.append(row)
    sid = child.session.session_id
    stores.sessions.save_session(child.session)
    stores.tasks.attach_segment(
        TaskId(parent), sid, predecessor_id=parent, reason=RolloverReason.RECOVERY
    )
    assert stores.tasks.task_id_for_session(sid) == TaskId(parent)
    assert stores.tasks.task_id_for_session(parent) == TaskId(parent)
    api = SessionReadApi(path, stores)
    assert api.get_session_stream(str(sid)).status_code == 409
    assert api.get_session_artifact_detail(str(sid), "candidate").status_code == 409
    assert route_active_task(stores, str(parent), api.get_session_artifacts).status_code == 409
    assert (
        route_active_task(
            stores,
            str(parent),
            lambda segment: api.get_session_artifact_content(segment, "candidate"),
        ).status_code
        == 409
    )

    class Connected:
        async def is_disconnected(self):
            raise AssertionError("parent strict identity must be checked before cursor/fanout")

    async def replay():
        return [
            row
            async for row in tail_session_events(
                database_path=path,
                stores=stores,
                session_id=sid,
                request=Connected(),
                after_sequence=-1,
            )
        ]

    assert asyncio.run(replay()) == []


def test_received_handoff_cannot_become_ordinary_when_both_parent_indexes_are_missing():
    from types import SimpleNamespace

    from zebra_agent_api.coverage_public_read import coverage_session_read_problem

    from tests.agent_integrations.test_ag_ui_coverage_projection import stream
    from tests.agent_integrations.test_coverage_public_events import event

    _, identity = stream()
    received = event(EventType.SESSION_HANDOFF_RECEIVED, 1, {}, identity.session_id)
    stores = SimpleNamespace(
        events=SimpleNamespace(list_for_session=lambda sid: (received,)),
        tasks=SimpleNamespace(task_id_for_session=lambda sid: None),
        handoffs=SimpleNamespace(get_lineage=lambda sid: ()),
    )
    result = coverage_session_read_problem(stores, identity.session_id)
    assert result.status_code == 409
    assert result.body["status"] == "coverage_identity_unavailable"
