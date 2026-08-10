from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agent_core.domain.host_authority import (
    HostContextEnvelope,
    HostResourceRef,
    HostTechnicalLimits,
)
from agent_core.domain.identifiers import ToolCallId
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_integrations.host_tools import (
    HostToolGateway,
    HostToolGatewayError,
    HostToolManifest,
    HostToolTransportError,
    HostToolTransportResponse,
    HostWorkloadIdentity,
    HttpHostToolTransport,
)

NOW = datetime(2026, 8, 11, 8, 0, tzinfo=UTC)


@dataclass
class _FakeTransport:
    responses: list[HostToolTransportResponse]
    calls: list[tuple[str, str, dict[str, str], dict[str, object] | None]] = field(
        default_factory=list
    )

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: Mapping[str, object] | None,
        timeout_seconds: float,
    ) -> HostToolTransportResponse:
        del timeout_seconds
        self.calls.append((method, url, dict(headers), None if body is None else dict(body)))
        return self.responses.pop(0)


def test_manifest_reuses_tool_contract_and_invokes_with_scope_receipt() -> None:
    transport = _FakeTransport(
        [
            HostToolTransportResponse(
                200,
                {"workloadIdentity": "trench-worker", "tools": [_tool_payload()]},
            ),
            HostToolTransportResponse(
                200,
                {"output": "event payload", "metadata": {"trace_id": "trace-1", "secret": "drop"}},
            ),
        ]
    )
    gateway = HostToolGateway(
        "https://trench.example",
        HostWorkloadIdentity("trench-worker", "tenant-1", "trench"),
        transport=transport,
    )
    context = _context()

    manifest = gateway.discover(context)
    result = gateway.invoke(_tool_call(), context, idempotency_key="invoke-1", manifest=manifest)

    assert manifest.get("event.get") is not None
    assert result.status is ToolCallStatus.EXECUTED
    assert result.output == "event payload"
    assert result.receipt is not None
    assert result.receipt.scopes == ("trench:event:read",)
    assert result.metadata["trace_id"] == "trace-1"
    assert "secret" not in result.metadata
    assert transport.calls[1][2]["X-Zebra-Namespace"] == "tenant-1"
    body = transport.calls[1][3]
    assert body is not None
    assert body["scopes"] == ["trench:event:read"]


def test_scope_resource_and_idempotency_boundaries_fail_before_transport() -> None:
    transport = _FakeTransport(
        [
            HostToolTransportResponse(
                200,
                {"workloadIdentity": "trench-worker", "tools": [_tool_payload()]},
            )
        ]
    )
    gateway = HostToolGateway(
        "https://trench.example",
        HostWorkloadIdentity("trench-worker", "tenant-1", "trench"),
        transport=transport,
    )
    context = _context(scopes=("trench:event:other",))
    manifest = HostToolManifest.from_payload(
        {"workloadIdentity": "trench-worker", "tools": [_tool_payload()]}
    )

    denied = gateway.invoke(_tool_call(), context, manifest=manifest, idempotency_key="invoke-1")
    missing_key = gateway.invoke(_tool_call(), _context(), manifest=manifest)

    assert denied.status is ToolCallStatus.FAILED
    assert denied.metadata["reason"] == "scope_denied"
    assert missing_key.metadata["reason"] == "idempotency_required"
    assert len(transport.calls) == 0


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (HostToolTransportResponse(502, {"error": "upstream"}), "host_http_error"),
        (HostToolTransportResponse(200, {"not_output": True}), "invalid_body"),
    ],
)
def test_http_and_invalid_body_failures_are_recoverable(
    response: HostToolTransportResponse, reason: str
) -> None:
    transport = _FakeTransport(
        [
            HostToolTransportResponse(
                200,
                {"workloadIdentity": "trench-worker", "tools": [_tool_payload()]},
            ),
            response,
        ]
    )
    gateway = HostToolGateway(
        "https://trench.example",
        HostWorkloadIdentity("trench-worker", "tenant-1", "trench"),
        transport=transport,
    )
    manifest = gateway.discover(_context())

    result = gateway.invoke(_tool_call(), _context(), manifest=manifest, idempotency_key="invoke-1")

    assert result.status is ToolCallStatus.FAILED
    assert result.metadata["reason"] == reason
    assert result.metadata["recoverable"] is True


def test_output_limit_and_manifest_integrity_fail_closed() -> None:
    payload = _tool_payload()
    payload["maxOutputBytes"] = 2
    transport = _FakeTransport(
        [
            HostToolTransportResponse(
                200,
                {"workloadIdentity": "trench-worker", "tools": [payload]},
            ),
            HostToolTransportResponse(200, {"output": "too long"}),
        ]
    )
    gateway = HostToolGateway(
        "https://trench.example",
        HostWorkloadIdentity("trench-worker", "tenant-1", "trench"),
        transport=transport,
    )
    manifest = gateway.discover(_context())
    result = gateway.invoke(_tool_call(), _context(), manifest=manifest, idempotency_key="invoke-1")

    assert result.metadata["reason"] == "output_too_large"
    with pytest.raises(HostToolGatewayError, match="digest"):
        HostToolManifest.from_payload(
            {
                "workloadIdentity": "trench-worker",
                "tools": [_tool_payload()],
                "manifestDigest": "0" * 64,
            }
        )


def test_http_transport_rejects_ssrf_targets_before_client() -> None:
    transport = HttpHostToolTransport(resolver=lambda _host: ("127.0.0.1",))

    with pytest.raises(HostToolTransportError, match="SSRF"):
        transport.request(
            "GET",
            "https://trench.example/manifest",
            headers={},
            body=None,
            timeout_seconds=1,
        )


def test_manifest_rejects_non_host_location_and_invoke_discovery_transport_failure() -> None:
    payload = _tool_payload()
    payload["executionLocation"] = "sandbox"
    with pytest.raises(HostToolGatewayError, match="not a Host tool"):
        HostToolManifest.from_payload({"workloadIdentity": "trench-worker", "tools": [payload]})

    class _FailingTransport(_FakeTransport):
        def request(self, *args: object, **kwargs: object) -> HostToolTransportResponse:
            raise HostToolTransportError("timeout", reason="timeout")

    gateway = HostToolGateway(
        "https://trench.example",
        HostWorkloadIdentity("trench-worker", "tenant-1", "trench"),
        transport=_FailingTransport([]),
    )
    result = gateway.invoke(_tool_call(), _context())

    assert result.status is ToolCallStatus.FAILED
    assert result.metadata["reason"] == "timeout"
    with pytest.raises(HostToolTransportError, match="HTTPS"):
        HttpHostToolTransport(resolver=lambda _host: ("8.8.8.8",)).request(
            "GET", "http://trench.example/manifest", headers={}, body=None, timeout_seconds=1
        )


def _tool_payload() -> dict[str, object]:
    return {
        "name": "event.get",
        "description": "Read one Event.",
        "requiredArguments": ["event_id"],
        "argumentProperties": {"event_id": {"type": "string"}},
        "scopes": ["trench:event:read"],
        "risk": "read",
        "timeoutSeconds": 5,
        "maxOutputBytes": 1_024,
        "idempotency": "required",
    }


def _tool_call() -> ToolCall:
    return ToolCall(
        tool_call_id=ToolCallId(uuid4()),
        name="event.get",
        arguments={"event_id": "evt-1"},
        created_at=NOW,
    )


def _context(
    *,
    scopes: tuple[str, ...] = ("trench:event:read",),
) -> HostContextEnvelope:
    return HostContextEnvelope(
        grant_id="grant-1",
        host_app_id="trench",
        namespace_id="tenant-1",
        workspace_ref="workspace-1",
        resource_refs=(HostResourceRef(type="event", id="evt-1"),),
        scopes=scopes,
        limits=HostTechnicalLimits(
            max_runtime_seconds=30,
            max_model_tokens=10_000,
            max_artifact_bytes=1_000_000,
        ),
        origin="https://trench.example",
        policy_version="host-policy-v1",
    )
