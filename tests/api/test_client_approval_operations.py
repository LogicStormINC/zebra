"""Public input/current authority checks; the PG suite proves atomic writes."""

from uuid import uuid4

import pytest
from zebra_agent_api.routes import RouteRequest

from tests.api.test_agui_bound_client_state import setup_surface


class ReadOnlyPort:
    def __init__(self, source):
        self.source = source
        self.reads = 0

    def __getattr__(self, name):
        return getattr(self.source, name)

    def approval_operation_unit(self, segment):
        raise AssertionError("read must not claim")

    def read_approval_operation(self, segment, key):
        self.reads += 1
        return None


def fixture(tmp_path):
    adapter, platform, headers, _, db, task = setup_surface(tmp_path)
    port = ReadOnlyPort(adapter.app.stores.events)
    object.__setattr__(adapter.app.stores, "events", port)
    headers = {**headers, "X-Zebra-Command-Segment": str(task)}
    return (
        adapter,
        platform,
        headers,
        f"/v1/tasks/{task}/runs/run-1/approval-operations/{uuid4()}",
        port,
    )


def test_read_is_original_observation_not_state_inference(tmp_path):
    adapter, _, headers, path, port = fixture(tmp_path)
    for _ in range(2):
        response = adapter.handle(RouteRequest("GET", path, headers=headers))
        assert response.status_code == 200, response
        assert response.body == {"status": "not_observed"}
    assert port.reads == 2


@pytest.mark.parametrize("case", ["body", "query", "segment", "session", "run", "observer"])
def test_bad_input_and_current_authority_never_read_or_write(tmp_path, case):
    adapter, _, headers, path, port = fixture(tmp_path)
    args = {}
    method = "GET"
    if case == "body":
        args["body"] = {}
    elif case == "query":
        args["query"] = {"key": "x"}
    elif case == "segment":
        headers["X-Zebra-Command-Segment"] = str(uuid4())
    elif case == "session":
        headers["X-Zebra-Client-Session"] = "forged"
    elif case == "run":
        path = path.replace("run-1", "wrong-run")
    else:
        method = "POST"
        args["body"] = {
            "decision": "approve",
            "expected_revision": 0,
            "operator": "user",
            "reason": "explicit",
        }
    response = adapter.handle(RouteRequest(method, path, headers=headers, **args))
    assert response.status_code in {400, 401, 403, 404, 409}, response
    assert port.reads == 0
