"""Manifest discovery and scope-bound Host Tool invocation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit

from agent_core.domain.host_authority import HostContextEnvelope, HostResourceRef
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_tools.contracts import ToolContract

from agent_integrations.host_tools.contracts import (
    HostToolGatewayError,
    HostToolInvocation,
    HostToolManifest,
    HostToolTransport,
    HostToolTransportError,
    HostWorkloadIdentity,
)
from agent_integrations.host_tools.http import HttpHostToolTransport


@dataclass
class HostToolGateway:
    endpoint: str
    workload_identity: HostWorkloadIdentity
    transport: HostToolTransport | None = None
    manifest: HostToolManifest | None = None

    def discover(self, context: HostContextEnvelope) -> HostToolManifest:
        self.workload_identity.assert_matches(context)
        transport = self.transport or HttpHostToolTransport()
        response = transport.request(
            "GET",
            _join_endpoint(self.endpoint, "/manifest"),
            headers=_headers(self.workload_identity, context),
            body=None,
            timeout_seconds=10,
        )
        if not 200 <= response.status_code < 300:
            raise HostToolGatewayError(
                "Host Tool manifest request was rejected",
                reason="manifest_http_error",
            )
        if not isinstance(response.body, Mapping):
            raise HostToolGatewayError("Host Tool manifest body is invalid", reason="invalid_body")
        try:
            manifest = HostToolManifest.from_payload(response.body)
        except HostToolGatewayError:
            raise
        if manifest.workload_identity != self.workload_identity.subject:
            raise HostToolGatewayError(
                "Host Tool manifest identity does not match the workload",
                reason="workload_identity_mismatch",
            )
        self.manifest = manifest
        return manifest

    def invoke(
        self,
        tool_call: ToolCall,
        context: HostContextEnvelope,
        *,
        idempotency_key: str | None = None,
        required_resource: HostResourceRef | None = None,
        manifest: HostToolManifest | None = None,
    ) -> ToolResult:
        try:
            self.workload_identity.assert_matches(context)
            active_manifest = manifest or self.manifest
            if active_manifest is None:
                active_manifest = self.discover(context)
            contract = active_manifest.get(tool_call.name)
            if contract is None:
                return _failure(tool_call, reason="unknown_host_tool")
            missing = [
                argument
                for argument in contract.required_arguments
                if argument not in tool_call.arguments
            ]
            if missing:
                return _failure(
                    tool_call,
                    reason="missing_required_argument",
                    detail=", ".join(sorted(missing)),
                )
            effective_scopes = tuple(sorted(set(contract.scopes) & set(context.scopes)))
            invocation = HostToolInvocation(
                tool_call=tool_call,
                contract=contract,
                context=context,
                identity=self.workload_identity,
                effective_scopes=effective_scopes,
                required_resource=required_resource,
                idempotency_key=idempotency_key,
            )
        except HostToolGatewayError as exc:
            return _failure(tool_call, reason=exc.reason)
        except HostToolTransportError as exc:
            return _failure(tool_call, reason=exc.reason, detail=str(exc))
        except (TimeoutError, ValueError) as exc:
            return _failure(tool_call, reason="transport_error", detail=str(exc))
        try:
            response = (self.transport or HttpHostToolTransport()).request(
                "POST",
                _join_endpoint(self.endpoint, f"/tools/{quote(contract.name, safe='')}/invoke"),
                headers=_headers(self.workload_identity, context),
                body=_invoke_body(invocation),
                timeout_seconds=contract.timeout_seconds,
            )
        except HostToolTransportError as exc:
            return _failure(
                tool_call,
                reason=exc.reason,
                detail=str(exc),
                contract=contract,
                scopes=effective_scopes,
                idempotency_key=idempotency_key,
            )
        except (TimeoutError, ValueError) as exc:
            return _failure(
                tool_call,
                reason="transport_error",
                detail=str(exc),
                contract=contract,
                scopes=effective_scopes,
                idempotency_key=idempotency_key,
            )
        if not 200 <= response.status_code < 300:
            return _failure(
                tool_call,
                reason="host_http_error",
                detail=str(response.status_code),
                contract=contract,
                scopes=effective_scopes,
                idempotency_key=idempotency_key,
                metadata={"http_status": response.status_code},
            )
        if not isinstance(response.body, Mapping):
            return _failure(
                tool_call,
                reason="invalid_body",
                contract=contract,
                scopes=effective_scopes,
                idempotency_key=idempotency_key,
            )
        output = response.body.get("output")
        if not isinstance(output, str):
            return _failure(
                tool_call,
                reason="invalid_body",
                contract=contract,
                scopes=effective_scopes,
                idempotency_key=idempotency_key,
            )
        output_bytes = len(output.encode())
        if output_bytes > contract.max_output_bytes:
            return _failure(
                tool_call,
                reason="output_too_large",
                detail=str(output_bytes),
                contract=contract,
                scopes=effective_scopes,
                idempotency_key=idempotency_key,
            )
        return ToolResult(
            tool_call_id=tool_call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=output,
            metadata={
                "route": "host_tool_gateway",
                "tool_name": contract.name,
                "manifest_digest": active_manifest.digest,
                "workload_identity": self.workload_identity.subject,
                "scope_intersection": list(effective_scopes),
                **_safe_metadata(response.body.get("metadata")),
            },
            receipt=contract.receipt(
                status="executed",
                output_bytes=output_bytes,
                idempotency_key=idempotency_key,
            ),
        )


def _invoke_body(invocation: HostToolInvocation) -> dict[str, object]:
    return {
        "toolCallId": str(invocation.tool_call.tool_call_id),
        "toolName": invocation.contract.name,
        "arguments": invocation.tool_call.arguments,
        "scopes": list(invocation.effective_scopes),
        "resources": [
            resource.model_dump(mode="json", by_alias=True)
            for resource in invocation.context.resource_refs
        ],
        "idempotencyKey": invocation.idempotency_key,
        "workloadIdentity": invocation.identity.subject,
    }


def _headers(identity: HostWorkloadIdentity, context: HostContextEnvelope) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Zebra-Workload-Identity": identity.subject,
        "X-Zebra-Host-App": identity.host_app_id,
        "X-Zebra-Namespace": identity.namespace_id,
        "X-Zebra-Grant-Id": context.grant_id,
    }


def _join_endpoint(endpoint: str, suffix: str) -> str:
    parsed = urlsplit(endpoint.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise HostToolGatewayError("Host Tool endpoint must be an HTTPS URL", reason="ssrf_blocked")
    if parsed.username is not None or parsed.password is not None:
        raise HostToolGatewayError(
            "Host Tool endpoint must not contain credentials", reason="ssrf_blocked"
        )
    if parsed.query or parsed.fragment:
        raise HostToolGatewayError(
            "Host Tool endpoint must not contain query or fragment", reason="ssrf_blocked"
        )
    base_path = parsed.path.rstrip("/")
    path = f"{base_path}{suffix}"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _failure(
    tool_call: ToolCall,
    *,
    reason: str,
    detail: str | None = None,
    contract: ToolContract | None = None,
    scopes: tuple[str, ...] = (),
    idempotency_key: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> ToolResult:
    result_metadata: dict[str, object] = {
        "route": "host_tool_gateway",
        "reason": reason,
        "recoverable": True,
    }
    if detail:
        result_metadata["detail"] = detail[:256]
    if metadata:
        result_metadata.update(_safe_metadata(metadata))
    receipt = None
    if contract is not None and scopes:
        receipt = contract.receipt(
            status="failed",
            output_bytes=0,
            idempotency_key=idempotency_key,
        )
    return ToolResult(
        tool_call_id=tool_call.tool_call_id,
        status=ToolCallStatus.FAILED,
        metadata=result_metadata,
        receipt=receipt,
    )


def _safe_metadata(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    safe: dict[str, object] = {}
    blocked = ("authorization", "token", "secret", "password", "credential")
    for key, item in value.items():
        if not isinstance(key, str) or any(word in key.lower() for word in blocked):
            continue
        if isinstance(item, str) and len(item) <= 256:
            safe[key] = item
        elif isinstance(item, bool | int | float) or item is None:
            safe[key] = item
    return safe
