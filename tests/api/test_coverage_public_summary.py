"""Candidate output cannot escape via Session/Task summary metadata."""

import pytest
from agent_core.domain.sessions import ApprovalContext
from zebra_agent_api.coverage_public_summary import coverage_public_summary
from zebra_agent_api.session_read import SessionReadApi
from zebra_agent_api.task_api import TaskReadApi

from tests.api.test_coverage_public_read import seed


@pytest.mark.parametrize("raw", [None, {}, "invalid"])
def test_summary_whitelist_refuses_private_and_future_fields(tmp_path, raw):
    stores, sid = seed(tmp_path / "events.sqlite", raw)
    private = {
        "session_id": str(sid),
        "status": "running",
        "title": "candidate title",
        "approval_context": {"assistant_message": "private"},
        "attachments": ["private"],
        "task_plan": "private",
        "future_field": "private",
    }
    assert coverage_public_summary(stores, sid, private) == {
        "session_id": str(sid),
        "status": "running",
        "title": "全量数据处理",
        "output_status": "coverage_report_required",
    }
    assert private["title"] == "candidate title"


def test_session_and_task_summary_callers_filter_candidate_context(tmp_path):
    path = tmp_path / "events.sqlite"
    stores, sid = seed(path, None)
    session = stores.sessions.get_session(sid)
    stores.sessions.save_session(
        session.model_copy(
            update={
                "approval_context": ApprovalContext(
                    tool_name="private",
                    reason="private",
                    policy_profile="private",
                    arguments={"private": "secret"},
                    assistant_message="candidate text",
                ),
            }
        )
    )
    responses = (
        SessionReadApi(path, stores).get_session(str(sid)),
        TaskReadApi(stores).get(str(sid)),
    )
    bodies = [response.body for response in responses]
    bodies.extend(TaskReadApi(stores).list({}).body["tasks"])
    assert all(response.status_code == 200 for response in responses)
    assert bodies and all("approval_context" not in body for body in bodies)
    assert all(body["output_status"] == "coverage_report_required" for body in bodies)
