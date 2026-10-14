from types import SimpleNamespace
from unittest.mock import Mock

from agent_core.ports.task_projection_checkpoints import CheckpointConflict, CheckpointNotReady
from zebra_agent_api.ag_ui_stream import prepare_agui_stream
from zebra_agent_api.ag_ui_task_view import stream_problem
from zebra_agent_api.stream_v2_http import prepare_v2


def test_temporary_preparation_is_retryable_without_relaxing_conflicts():
    path = "/agui/threads/67fee462-9f30-4ece-8e60-501a5ef3e177/runs/probe/stream"
    for error, code, retryable in (
        (CheckpointNotReady("source preparing"), "projection_not_ready", True),
        (CheckpointConflict("source conflicts"), "projection_conflict", False),
    ):
        tasks = SimpleNamespace(read_task_header=Mock(side_effect=error))
        response = prepare_agui_stream(
            SimpleNamespace(deployment_namespace="test", tasks=tasks), path, {}
        )
        assert response.status_code == 409 and response.body["code"] == code
        assert (response.body.get("retryable") is True) is retryable
    response = stream_problem(400, "projection_not_ready", "invalid", path)
    assert response.body.get("retryable") is not True


def test_v2_initialization_retries_only_preparing_sources():
    path = "/agui/threads/67fee462-9f30-4ece-8e60-501a5ef3e177/runs/probe/stream"
    for error, code, retryable in (
        (CheckpointNotReady("no initial checkpoint"), "projection_not_ready", True),
        (ValueError("scope conflict"), "invalid_cursor", False),
        (RuntimeError("broken source"), "stream_source_unavailable", False),
    ):
        reader = SimpleNamespace(authority=SimpleNamespace(bind=Mock(side_effect=error)))
        api = SimpleNamespace(
            stream_v2_reader=reader,
            stores=SimpleNamespace(deployment_namespace="test", tasks=Mock()),
        )
        response = prepare_v2(api, path, {}, object())
        assert response.body["code"] == code
        assert (response.body.get("retryable") is True) is retryable
