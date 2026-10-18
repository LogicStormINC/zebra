"""File reads must not require granting execution authority."""

import pytest
from zebra_agent_api.host_auth import _required_scopes_for_request
from zebra_agent_api.http_host_auth import HostGrantHttpRequest


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize(
    "suffix", ["", "/file", "/file/content", "/file/download", "/file/preview"]
)
def test_artifact_reads_require_only_artifact_scope(method, suffix):
    request = HostGrantHttpRequest(method, f"/tasks/task/artifacts{suffix}", None, "Bearer token")
    assert _required_scopes_for_request(request) == ("artifact.read",)


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/tasks/task/artifacts/file/prune"),
        ("POST", "/tasks/task/messages"),
        ("GET", "/tasks/task"),
    ],
)
def test_artifact_scope_never_enables_non_artifact_routes(method, path):
    request = HostGrantHttpRequest(method, path, None, "Bearer token")
    assert _required_scopes_for_request(request) != ("artifact.read",)
