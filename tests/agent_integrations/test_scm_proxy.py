import pytest
from agent_integrations import (
    ScmProxyRequest,
    ScmProxyResponse,
    ScmProxyTransport,
    build_github_pull_request_proxy_request,
)


def test_scm_proxy_request_normalizes_headers_and_json_fields() -> None:
    request = ScmProxyRequest(
        provider=" github ",
        action=" pull_request.create ",
        endpoint=" https://proxy.example/scm ",
        method=" post ",
        headers=(
            ("X-Zebra-Trace", "trace-123"),
            ("Accept", "application/json"),
        ),
        body={"b": ["x", {"z": True}], "a": 1},
        metadata={"credential_backend": "github_app", "credential_source": "broker"},
    )

    assert request.provider == "github"
    assert request.action == "pull_request.create"
    assert request.endpoint == "https://proxy.example/scm"
    assert request.method == "POST"
    assert request.headers == (
        ("Accept", "application/json"),
        ("X-Zebra-Trace", "trace-123"),
    )
    assert request.header_map() == {
        "Accept": "application/json",
        "X-Zebra-Trace": "trace-123",
    }
    assert request.to_serializable() == {
        "provider": "github",
        "action": "pull_request.create",
        "endpoint": "https://proxy.example/scm",
        "method": "POST",
        "headers": [
            {"name": "Accept", "value": "application/json"},
            {"name": "X-Zebra-Trace", "value": "trace-123"},
        ],
        "body": {"a": 1, "b": ["x", {"z": True}]},
        "metadata": {
            "credential_backend": "github_app",
            "credential_source": "broker",
        },
    }


def test_scm_proxy_request_rejects_duplicate_headers() -> None:
    with pytest.raises(ValueError, match="duplicate header"):
        ScmProxyRequest(
            provider="github",
            action="pull_request.create",
            endpoint="https://proxy.example/scm",
            headers=(("Accept", "application/json"), ("accept", "text/plain")),
        )


def test_scm_proxy_request_rejects_non_json_values() -> None:
    with pytest.raises(ValueError, match="JSON-serializable"):
        ScmProxyRequest(
            provider="github",
            action="pull_request.create",
            endpoint="https://proxy.example/scm",
            body={"callback": object()},  # type: ignore[dict-item]
        )


def test_scm_proxy_response_normalizes_serializable_shape() -> None:
    response = ScmProxyResponse(
        status_code=201,
        headers=(("x-request-id", "req-123"),),
        body={"url": "https://github.example/pulls/1", "draft": False},
        metadata={"provider": "github"},
    )

    assert response.header_map() == {"x-request-id": "req-123"}
    assert response.to_serializable() == {
        "status_code": 201,
        "headers": [{"name": "x-request-id", "value": "req-123"}],
        "body": {"draft": False, "url": "https://github.example/pulls/1"},
        "metadata": {"provider": "github"},
    }


def test_scm_proxy_response_rejects_invalid_status_code() -> None:
    with pytest.raises(ValueError, match="status_code"):
        ScmProxyResponse(status_code=99, body={})


def test_build_github_pull_request_proxy_request_builds_deterministic_shape() -> None:
    request = build_github_pull_request_proxy_request(
        endpoint="https://proxy.example/scm",
        headers={
            "X-GitHub-Api-Version": "2022-11-28",
            "Accept": "application/vnd.github+json",
        },
        body={
            "title": "Add feature",
            "base": "main",
            "head": "feature/zebra",
        },
        credential_source="broker",
        credential_backend="environment",
    )

    assert request.to_serializable() == {
        "provider": "github",
        "action": "pull_request.create",
        "endpoint": "https://proxy.example/scm",
        "method": "POST",
        "headers": [
            {"name": "Accept", "value": "application/vnd.github+json"},
            {"name": "X-GitHub-Api-Version", "value": "2022-11-28"},
        ],
        "body": {
            "base": "main",
            "head": "feature/zebra",
            "title": "Add feature",
        },
        "metadata": {
            "credential_backend": "environment",
            "credential_source": "broker",
        },
    }


def test_scm_proxy_transport_protocol_accepts_fake() -> None:
    transport = _FakeProxyTransport()

    typed_transport: ScmProxyTransport = transport

    response = typed_transport.execute(
        ScmProxyRequest(
            provider="github",
            action="pull_request.create",
            endpoint="https://proxy.example/scm",
        )
    )

    assert response.status_code == 202


class _FakeProxyTransport:
    def execute(self, request: ScmProxyRequest) -> ScmProxyResponse:
        assert request.provider == "github"
        return ScmProxyResponse(
            status_code=202,
            body={"accepted": True},
            metadata={"transport": "fake-proxy"},
        )
