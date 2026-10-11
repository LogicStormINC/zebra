"""A partial contiguous child index cannot replace retained root authority."""

import sqlite3
from dataclasses import replace
from types import SimpleNamespace

import pytest
from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.domain.agent_tasks import RolloverReason
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import TaskId
from agent_integrations.ag_ui import AgUiProjectionError
from zebra_agent_api.ag_ui_task_view import canonical_task_view
from zebra_agent_api.coverage_public_read import coverage_session_read_problem
from zebra_agent_api.session_read import SessionReadApi
from zebra_agent_api.task_api import TaskReadApi

from tests.agent_integrations.test_coverage_public_events import event
from tests.api.test_coverage_public_read import seed


@pytest.mark.parametrize("relabel", [False, True])
def test_missing_root_membership_refuses_raw_and_artifact_reads(tmp_path, relabel):
    path = tmp_path / "scratch.sqlite"
    stores, parent = seed(path, None)
    child = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title="Continuation",
            user_input="continue",
            workspace_root=tmp_path,
        )
    )
    sid = child.session.session_id
    for row in child.events:
        stores.events.append(row)
    stores.events.append(
        event(
            EventType.SESSION_HANDOFF_RECEIVED,
            len(child.events),
            {"root_session_id": str(parent), "parent_session_id": str(parent), "stage_index": 1},
            sid,
        )
    )
    stores.events.append(
        event(
            EventType.MODEL_RESPONSE_RECEIVED,
            len(child.events) + 1,
            {"assistant_message": "PRIVATE_CANDIDATE"},
            sid,
        )
    )
    stores.sessions.save_session(child.session)
    stores.tasks.attach_segment(
        TaskId(parent),
        sid,
        predecessor_id=parent,
        reason=RolloverReason.RECOVERY,
    )
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM task_event_index WHERE task_id=?", (str(parent),))
        connection.execute("DELETE FROM execution_segments WHERE session_id=?", (str(parent),))
        if relabel:
            connection.execute(
                "UPDATE execution_segments SET task_id=?,segment_index=0,predecessor_id=NULL "
                "WHERE session_id=?",
                (str(sid), str(sid)),
            )
    task_id = TaskId(sid if relabel else parent)
    with pytest.raises(AgUiProjectionError, match="membership"):
        canonical_task_view(stores, task_id)
    api = SessionReadApi(path, stores)
    for response in (
        api.get_session_stream(str(sid)),
        api.get_session_artifacts(str(sid)),
        api.get_session_artifact_content(str(sid), "candidate"),
        TaskReadApi(stores).stream(str(task_id)),
    ):
        assert response.status_code == 409
        assert response.body["status"] == "coverage_identity_unavailable"
        assert "PRIVATE_CANDIDATE" not in str(response.body)


def test_partial_index_high_watermark_cannot_hide_retained_strict_admission(tmp_path):
    path = tmp_path / "prefix.sqlite"
    stores, root = seed(path, None)
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
        TaskId(root),
        sid,
        predecessor_id=root,
        reason=RolloverReason.RECOVERY,
    )
    actual = stores.tasks
    partial = tuple(
        replace(row, task_sequence=index)
        for index, row in enumerate(
            item
            for item in actual.read_events(TaskId(root), -1)
            if not (
                item.event.event_type is EventType.TASK_PREPARED
                and "coverage_admission" in item.event.payload
            )
        )
    )
    seam = replace(
        stores,
        tasks=SimpleNamespace(
            segments=actual.segments,
            task_id_for_session=actual.task_id_for_session,
            read_events=lambda task_id, after_sequence: partial,
        ),
    )
    with pytest.raises(AgUiProjectionError, match="align"):
        canonical_task_view(seam, TaskId(root))
    assert coverage_session_read_problem(seam, sid).status_code == 409
    assert SessionReadApi(path, seam).get_session_stream(str(sid)).status_code == 409
