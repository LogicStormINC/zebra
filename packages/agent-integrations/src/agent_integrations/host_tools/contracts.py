"""Typed Host Tool wire contracts built on the existing ToolContract model."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from agent_core.domain.host_authority import HostContextEnvelope, HostResourceRef
from agent_core.domain.tools import ToolCall
from agent_tools.contracts import ToolContract, ToolExecutionLocation, ToolIdempotency, ToolRisk

MAX_MANIFEST_TOOLS = 128
MAX_MANIFEST_BYTES = 256 * 1024
MAX_WORKLOAD_IDENTITY_LENGTH = 512


class HostToolGatewayError(ValueError):
    """Raised when a Host manifest or invocation contract is invalid."""

    def __init__(self, message: str, *, reason: str = "host_tool_contract") -> None:
        super().__init__(message)
        self.reason = reason


class HostToolTransportError(RuntimeError):
    """Raised when the Host transport cannot produce a bounded response."""

    def __init__(self, message: str, *, reason: str = "host_transport_error") -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class HostWorkloadIdentity:
    """Non-secret workload identity bound to one Host namespace."""

    subject: str
    namespace_id: str
    host_app_id: str

    def __post_init__(self) -> None:
        for field_name in ("subject", "namespace_id", "host_app_id"):
            raw_value = getattr(self, field_name)
            if not isinstance(raw_value, str):
                raise ValueError(f"{field_name} must be text")
            value = raw_value.strip()
            if not value or len(value) > MAX_WORKLOAD_IDENTITY_LENGTH:
                raise ValueError(f"{field_name} must be bounded and non-blank")
            object.__setattr__(self, field_name, value)

    def assert_matches(self, context: HostContextEnvelope) -> None:
        if self.namespace_id != context.namespace_id or self.host_app_id != context.host_app_id:
            raise HostToolGatewayError(
                "workload identity does not match Host Grant namespace",
                reason="workload_identity_mismatch",
            )


@dataclass(frozen=True, slots=True)
class HostToolManifest:
    workload_identity: str
    tools: tuple[ToolContract, ...]
    digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.workload_identity, str):
            raise HostToolGatewayError("manifest workload identity is invalid")
        identity = self.workload_identity.strip()
        if not identity or len(identity) > MAX_WORKLOAD_IDENTITY_LENGTH:
            raise HostToolGatewayError("manifest workload identity is invalid")
        if not self.tools or len(self.tools) > MAX_MANIFEST_TOOLS:
            raise HostToolGatewayError("manifest tool count is outside its bounds")
        names = tuple(tool.name for tool in self.tools)
        if len(set(names)) != len(names):
            raise HostToolGatewayError("manifest contains duplicate tool names")
        if any(tool.execution_location is not ToolExecutionLocation.HOST for tool in self.tools):
            raise HostToolGatewayError("manifest entries must be Host tools")
        if len(self.digest) != 64 or any(char not in "0123456789abcdef" for char in self.digest):
            raise HostToolGatewayError("manifest digest is invalid")
        object.__setattr__(self, "workload_identity", identity)

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> HostToolManifest:
        try:
            identity = _required_text(
                payload.get("workloadIdentity", payload.get("workload_identity")),
                "workload_identity",
            )
            raw_tools = payload["tools"]
        except KeyError as exc:
            raise HostToolGatewayError("manifest is missing required fields") from exc
        if not isinstance(raw_tools, Sequence) or isinstance(raw_tools, str | bytes):
            raise HostToolGatewayError("manifest tools must be an array")
        if len(raw_tools) > MAX_MANIFEST_TOOLS:
            raise HostToolGatewayError("manifest contains too many tools")
        tools = tuple(_tool_contract(item) for item in raw_tools)
        canonical = {
            "workloadIdentity": identity,
            "tools": [_tool_payload(tool) for tool in tools],
        }
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        if len(encoded) > MAX_MANIFEST_BYTES:
            raise HostToolGatewayError("manifest exceeds its size bound")
        digest = hashlib.sha256(encoded).hexdigest()
        supplied = payload.get("manifestDigest", payload.get("manifest_digest"))
        if supplied is not None and supplied != digest:
            raise HostToolGatewayError("manifest digest does not match its contents")
        return cls(workload_identity=identity, tools=tools, digest=digest)

    def get(self, name: str) -> ToolContract | None:
        return next((tool for tool in self.tools if tool.name == name), None)


@dataclass(frozen=True, slots=True)
class HostToolTransportResponse:
    status_code: int
    body: object
    content_type: str = "application/json"

    def __post_init__(self) -> None:
        if not 100 <= self.status_code <= 599:
            raise ValueError("Host transport status_code is invalid")


class HostToolTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: Mapping[str, object] | None,
        timeout_seconds: float,
    ) -> HostToolTransportResponse: ...


@dataclass(frozen=True, slots=True)
class HostToolInvocation:
    tool_call: ToolCall
    contract: ToolContract
    context: HostContextEnvelope
    identity: HostWorkloadIdentity
    effective_scopes: tuple[str, ...]
    required_resource: HostResourceRef | None = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.effective_scopes:
            raise HostToolGatewayError(
                "Host Tool scope intersection is empty", reason="scope_denied"
            )
        self.identity.assert_matches(self.context)
        if set(self.contract.scopes) - set(self.context.scopes):
            raise HostToolGatewayError(
                "Host Grant does not cover the Tool manifest scopes",
                reason="scope_denied",
            )
        if (
            self.required_resource is not None
            and self.required_resource not in self.context.resource_refs
        ):
            raise HostToolGatewayError(
                "Host Grant does not cover the requested resource",
                reason="resource_denied",
            )
        if self.contract.idempotency is ToolIdempotency.REQUIRED and not self.idempotency_key:
            raise HostToolGatewayError(
                "Host Tool requires an idempotency key",
                reason="idempotency_required",
            )


def _tool_contract(raw: object) -> ToolContract:
    if not isinstance(raw, Mapping):
        raise HostToolGatewayError("manifest tool entry must be an object")
    try:
        scopes = _text_sequence(raw.get("scopes"), "tool scopes")
        required = _text_sequence(
            raw.get("requiredArguments", raw.get("required_arguments")),
            "required arguments",
            allow_empty=True,
        )
        argument_properties = raw.get("argumentProperties", raw.get("argument_properties", {}))
        if not isinstance(argument_properties, Mapping):
            raise HostToolGatewayError("tool argument properties must be an object")
        declared_location = raw.get("executionLocation", raw.get("execution_location"))
        if declared_location is not None and declared_location != ToolExecutionLocation.HOST.value:
            raise HostToolGatewayError("manifest entry is not a Host tool")
        normalized_properties: dict[str, Mapping[str, object]] = {}
        for key, value in argument_properties.items():
            if not isinstance(key, str) or not isinstance(value, Mapping):
                raise HostToolGatewayError("tool argument properties must be objects")
            normalized_properties[key] = value
        risk = ToolRisk(str(raw.get("risk", ToolRisk.READ.value)))
        idempotency = ToolIdempotency(str(raw.get("idempotency", ToolIdempotency.NONE.value)))
        timeout_seconds = _bounded_int(
            raw.get("timeoutSeconds", raw.get("timeout_seconds", 30)),
            "timeout_seconds",
        )
        max_output_bytes = _bounded_int(
            raw.get("maxOutputBytes", raw.get("max_output_bytes", 32_768)),
            "max_output_bytes",
        )
        return ToolContract(
            name=_required_text(raw.get("name"), "tool name"),
            description=str(raw.get("description", "")),
            required_arguments=required,
            argument_properties={key: dict(value) for key, value in normalized_properties.items()},
            parallel_safe=_optional_bool(
                raw.get("parallelSafe", raw.get("parallel_safe", False)),
                "parallel_safe",
            ),
            capability_version=str(
                raw.get("capabilityVersion", raw.get("capability_version", "1"))
            ),
            execution_location=ToolExecutionLocation.HOST,
            scopes=scopes,
            risk=risk,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
            idempotency=idempotency,
            receipt_schema_version=str(raw.get("receiptSchemaVersion", "1")),
        )
    except HostToolGatewayError:
        raise
    except (TypeError, ValueError) as exc:
        raise HostToolGatewayError("manifest tool entry is invalid") from exc


def _tool_payload(tool: ToolContract) -> dict[str, object]:
    return {
        "name": tool.name,
        "description": tool.description,
        "requiredArguments": list(tool.required_arguments),
        "argumentProperties": {key: dict(value) for key, value in tool.argument_properties.items()},
        "parallelSafe": tool.parallel_safe,
        "capabilityVersion": tool.capability_version,
        "executionLocation": tool.execution_location.value,
        "scopes": list(tool.scopes),
        "risk": tool.risk.value,
        "timeoutSeconds": tool.timeout_seconds,
        "maxOutputBytes": tool.max_output_bytes,
        "idempotency": tool.idempotency.value,
        "receiptSchemaVersion": tool.receipt_schema_version,
    }


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HostToolGatewayError(f"{field_name} must be non-blank")
    return value.strip()


def _text_sequence(value: object, field_name: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if value is None and allow_empty:
        return ()
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise HostToolGatewayError(f"{field_name} must be an array")
    normalized = tuple(_required_text(item, field_name) for item in value)
    if not allow_empty and not normalized:
        raise HostToolGatewayError(f"{field_name} must not be empty")
    if len(set(normalized)) != len(normalized):
        raise HostToolGatewayError(f"{field_name} must not contain duplicates")
    return normalized


def _bounded_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise HostToolGatewayError(f"{field_name} must be a positive integer")
    return value


def _optional_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise HostToolGatewayError(f"{field_name} must be a boolean")
    return value
