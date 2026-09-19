"""Manifest discovery and scope-bound Host Tool invocation."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit, urlunsplit

from agent_core.domain.effect_dispatch import EffectBusinessOutcome, EffectTransportOutcome
from agent_core.domain.host_authority import HostContextEnvelope, HostResourceRef
from agent_core.domain.host_effect_receipts import HostEffectReceipt, HostEffectStatus
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult, ToolRisk
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
    shared_secret: str | None = None
    transport: HostToolTransport | None = None
    manifest: HostToolManifest | None = None

    def discover(self, context: HostContextEnvelope) -> HostToolManifest:
        _ensure_context_live(context)
        self.workload_identity.assert_matches(context)
        transport = self.transport or HttpHostToolTransport()
        url = _join_endpoint(self.endpoint, "/manifest")
        response = transport.request(
            "GET",
            url,
            headers=_headers(
                self.workload_identity,
                context,
                method="GET",
                path=urlsplit(url).path,
                body=None,
                host_app_id=self.workload_identity.host_app_id,
                namespace_id=self.workload_identity.namespace_id,
                shared_secret=self.shared_secret,
            ),
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
            _ensure_context_live(context)
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
        except TimeoutError as exc:
            return _failure(tool_call, reason="timeout", detail=str(exc))
        except ValueError as exc:
            return _failure(tool_call, reason="transport_error", detail=str(exc))
        try:
            url = _join_endpoint(self.endpoint, f"/tools/{quote(contract.name, safe='')}/invoke")
            body = _invoke_body(invocation)
            response = (self.transport or HttpHostToolTransport()).request(
                "POST",
                url,
                headers=_headers(
                    self.workload_identity,
                    context,
                    method="POST",
                    path=urlsplit(url).path,
                    body=body,
                    host_app_id=self.workload_identity.host_app_id,
                    namespace_id=self.workload_identity.namespace_id,
                    shared_secret=self.shared_secret,
                ),
                body=body,
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
        except TimeoutError as exc:
            return _failure(
                tool_call,
                reason="timeout",
                detail=str(exc),
                contract=contract,
                scopes=effective_scopes,
                idempotency_key=idempotency_key,
            )
        except ValueError as exc:
            return _failure(
                tool_call,
                reason="transport_error",
                detail=str(exc),
                contract=contract,
                scopes=effective_scopes,
                idempotency_key=idempotency_key,
            )
        if not 200 <= response.status_code < 300:
            detail, error_code = _safe_http_error(response.body)
            return _failure(
                tool_call,
                reason="host_http_error",
                detail=detail or str(response.status_code),
                contract=contract,
                scopes=effective_scopes,
                idempotency_key=idempotency_key,
                metadata={
                    "http_status": response.status_code,
                    **({"http_error_code": error_code} if error_code else {}),
                },
            )
        if not isinstance(response.body, Mapping):
            return _failure(
                tool_call,
                reason="invalid_body",
                contract=contract,
                scopes=effective_scopes,
                idempotency_key=idempotency_key,
            )
        effect_metadata: dict[str, object] = {}
        if contract.risk is not ToolRisk.READ:
            effect_metadata = _host_effect_metadata(response.body)
            business_outcome = effect_metadata["business_outcome"]
            if business_outcome != EffectBusinessOutcome.APPLIED.value:
                return _failure(
                    tool_call,
                    reason=(
                        "host_business_rejected"
                        if business_outcome == EffectBusinessOutcome.REJECTED.value
                        else "host_effect_unconfirmed"
                    ),
                    contract=contract,
                    scopes=effective_scopes,
                    idempotency_key=idempotency_key,
                    metadata=effect_metadata,
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
                **effect_metadata,
            },
            receipt=contract.receipt(
                status="executed",
                output_bytes=output_bytes,
                idempotency_key=idempotency_key,
            ),
        )


def _invoke_body(invocation: HostToolInvocation) -> dict[str, object]:
    body: dict[str, object] = {
        "toolCallId": str(invocation.tool_call.tool_call_id),
        "toolName": invocation.contract.name,
        "arguments": invocation.tool_call.arguments,
        "scopes": list(invocation.effective_scopes),
        "resources": [
            resource.model_dump(mode="json", by_alias=True)
            for resource in invocation.context.resource_refs
        ],
        "workloadIdentity": invocation.identity.subject,
    }
    if invocation.idempotency_key is not None:
        body["idempotencyKey"] = invocation.idempotency_key
    return body


def _headers(
    identity: HostWorkloadIdentity,
    context: HostContextEnvelope,
    *,
    method: str,
    path: str,
    body: Mapping[str, object] | None,
    host_app_id: str,
    namespace_id: str,
    shared_secret: str | None,
) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Zebra-Workload-Identity": identity.subject,
        "X-Zebra-Host-App": identity.host_app_id,
        "X-Zebra-Namespace": identity.namespace_id,
        "X-Zebra-Grant-Id": context.grant_id,
        "X-Zebra-Workspace-Ref": context.workspace_ref,
    }
    if shared_secret:
        headers["X-Zebra-Host-Auth"] = hmac.new(
            shared_secret.encode(),
            _signature_input(
                method=method,
                path=path,
                grant_id=context.grant_id,
                workspace_ref=context.workspace_ref,
                host_app_id=host_app_id,
                namespace_id=namespace_id,
                body=body,
            ),
            hashlib.sha256,
        ).hexdigest()
    return headers


def _signature_input(
    *,
    method: str,
    path: str,
    grant_id: str,
    workspace_ref: str,
    host_app_id: str,
    namespace_id: str,
    body: Mapping[str, object] | None,
) -> bytes:
    encoded = json.dumps(
        body or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return (
        f"{method.upper()}\n{path}\n{grant_id}\n{workspace_ref}\n"
        f"{host_app_id}\n{namespace_id}\n{encoded}"
    ).encode()


def _ensure_context_live(context: HostContextEnvelope) -> None:
    if context.expires_at is not None and datetime.now(UTC) >= context.expires_at:
        raise HostToolGatewayError("Host Grant has expired", reason="grant_expired")


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


def _safe_http_error(body: object) -> tuple[str | None, str | None]:
    """Expose bounded business diagnostics while removing secret/path leakage."""
    if not isinstance(body, Mapping):
        return None, None
    detail: str | None = None
    for key in ("detail", "message", "error"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            candidate = " ".join(value.split())
            candidate = re.sub(
                r"(?i)(?<!\w)(bearer|basic|api[_-]?key|access[_-]?token|client[_-]?secret|token|secret|password|credential|authorization)\s*[:=]\s*\S+",
                r"\1=<redacted>",
                candidate,
            )
            candidate = re.sub(
                r"(?<![\w])/(?:Users|home|app|workspace|tmp|var|srv|opt|mnt)/[^\s,;]+",
                "<path>",
                candidate,
            )
            if "<redacted>" not in candidate and re.search(
                r"\beyJ[a-zA-Z0-9_-]{20,}\.[^\s]+", candidate
            ):
                candidate = ""
            if candidate and not candidate.lower().startswith(("traceback", "stack trace")):
                detail = candidate[:256]
            break
    code = body.get("code")
    return detail, code.strip()[:128] if isinstance(code, str) and code.strip() else None


def _host_effect_metadata(body: Mapping[str, object]) -> dict[str, object]:
    nested = body.get("metadata")
    metadata = nested if isinstance(nested, Mapping) else {}

    def value(*keys: str) -> object:
        for source in (body, metadata):
            for key in keys:
                candidate = source.get(key)
                if candidate is not None:
                    return candidate
        return None

    raw_status = value("effectStatus", "effect_status")
    provider_operation_id = value("providerOperationId", "provider_operation_id")
    business_revision = value("businessRevision", "business_revision")
    raw_status_text = raw_status if isinstance(raw_status, str) else ""
    normalized_status = {
        "applied": HostEffectStatus.SUCCEEDED,
        "rejected": HostEffectStatus.FAILED_NO_EFFECT,
    }.get(raw_status_text, raw_status_text)
    receipt: HostEffectReceipt | None = None
    try:
        receipt = HostEffectReceipt(
            provider_operation_id=(
                provider_operation_id.strip()
                if isinstance(provider_operation_id, str)
                else ""
            ),
            business_revision=(
                business_revision.strip()
                if isinstance(business_revision, str) and business_revision.strip()
                else None
            ),
            effect_status=HostEffectStatus(str(normalized_status)),
            evidence_digest=(
                str(value("evidenceDigest", "evidence_digest"))[:128]
                if value("evidenceDigest", "evidence_digest") is not None
                else None
            ),
            received_at=datetime.now(UTC),
        )
    except ValueError:
        pass
    applied = receipt is not None and receipt.effect_status is HostEffectStatus.SUCCEEDED
    rejected = receipt is not None and receipt.effect_status is HostEffectStatus.FAILED_NO_EFFECT
    outcome = (
        EffectBusinessOutcome.APPLIED
        if applied
        else EffectBusinessOutcome.REJECTED
        if rejected
        else EffectBusinessOutcome.UNKNOWN
    )
    result: dict[str, object] = {
        "transport_outcome": EffectTransportOutcome.RETURNED.value,
        "business_outcome": outcome.value,
    }
    if isinstance(provider_operation_id, str) and provider_operation_id.strip():
        result["provider_operation_id"] = provider_operation_id.strip()[:256]
        result["mutation_effect_id"] = provider_operation_id.strip()[:256]
    if isinstance(business_revision, str) and business_revision.strip():
        result["business_revision"] = business_revision.strip()[:256]
        result["commit_version"] = business_revision.strip()[:256]
    if receipt is not None:
        result["host_effect_receipt"] = receipt.model_dump(mode="json")
        result["host_effect_receipt_digest"] = receipt.receipt_digest
    return result


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
    result_metadata.update(_failure_outcomes(reason, result_metadata))
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


def _failure_outcomes(reason: str, metadata: Mapping[str, object]) -> dict[str, str]:
    if "transport_outcome" in metadata and "business_outcome" in metadata:
        return {}
    if reason == "timeout":
        return {
            "transport_outcome": EffectTransportOutcome.TIMED_OUT.value,
            "business_outcome": EffectBusinessOutcome.UNKNOWN.value,
        }
    if reason in {"transport_error", "host_transport_error", "manifest_http_error"}:
        return {
            "transport_outcome": EffectTransportOutcome.UNAVAILABLE.value,
            "business_outcome": EffectBusinessOutcome.UNKNOWN.value,
        }
    status = metadata.get("http_status")
    rejected = isinstance(status, int) and 400 <= status < 500
    return {
        "transport_outcome": EffectTransportOutcome.RETURNED.value,
        "business_outcome": (
            EffectBusinessOutcome.REJECTED.value
            if rejected
            or reason
            in {
                "unknown_host_tool",
                "missing_required_argument",
                "scope_denied",
                "resource_denied",
                "idempotency_required",
                "grant_expired",
            }
            else EffectBusinessOutcome.UNKNOWN.value
        ),
    }


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
