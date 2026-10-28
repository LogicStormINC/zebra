"""Private Host control probe over the existing pinned, authenticated tool transport."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from time import monotonic
from uuid import UUID

import httpx
from agent_core.domain.execution_authority import ExecutionAuthorityResolutionError
from agent_core.domain.identifiers import ToolCallId
from agent_core.domain.task_bindings import TaskBindingSnapshot, require_task_host_context
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_core.ports.host_connector_registry import HostConnectorRegistryPort
from agent_core.ports.host_credential_resolver import HostWorkloadCredentialResolverPort
from agent_integrations.host_tools import HostToolManifest
from agent_integrations.host_tools.http import HttpHostToolTransport
from pydantic import BaseModel, ConfigDict, Field
from zebra_agent_config.host_authority_settings import HostExecutionAuthoritySettings

from zebra_agent_worker.host_gateway_resolution import resolve_pinned_gateway

_ARGUMENTS = ("task_id", "thread_id", "run_id", "principal", "workspace_ref", "expires_at")


class HostAuthorityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    decision: str = Field(pattern="^allowed$")
    identity: dict[str, str] = Field(min_length=5, max_length=32)
    metadata_digest: str = Field(pattern="^[0-9a-f]{64}$")
    expires_at: datetime


class HostAuthorityProbe:
    def __init__(
        self,
        binding: TaskBindingSnapshot,
        registry: HostConnectorRegistryPort,
        credentials: HostWorkloadCredentialResolverPort,
        *,
        task_id: str,
        settings: HostExecutionAuthoritySettings,
        client: httpx.Client | None = None,
    ) -> None:
        self.binding = TaskBindingSnapshot.model_validate(binding.model_dump(mode="json"))
        self.registry, self.credentials, self.client = registry, credentials, client
        self.settings = settings
        context = self.binding.host_capability.host_context
        if (
            context is None
            or context.expires_at is None
            or settings.required_scope not in context.scopes
        ):
            raise ExecutionAuthorityResolutionError("Host control requires bound context and scope")
        self.context = context
        self.expires_at = context.expires_at
        thread = require_task_host_context(
            self.binding, self.context, task_id=str(task_id), now=datetime.now(UTC)
        )
        refs: dict[str, str | None] = {}
        for ref in self.context.resource_refs:
            if ref.resource_type in refs:
                refs[ref.resource_type] = None
            else:
                refs[ref.resource_type] = ref.resource_id
        if not refs.get("run") or not refs.get("principal"):
            raise ExecutionAuthorityResolutionError(
                "Host control requires unique Run and principal"
            )
        assert refs["run"] is not None and refs["principal"] is not None
        self.arguments = dict(
            task_id=str(task_id),
            thread_id=thread.resource_id,
            run_id=refs["run"],
            principal=refs["principal"],
            workspace_ref=self.context.workspace_ref,
            expires_at=self.expires_at.isoformat(),
        )
        self.expected_identity = {
            key: value for key, value in self.arguments.items() if key != "expires_at"
        }
        self.resource_identity = refs
        self.metadata_digest: str | None = None

    def check(self) -> datetime:
        """No positive cache. Every call rechecks the current connector and Host identity."""
        now = datetime.now(UTC)
        host = self.binding.host_capability
        if now >= self.expires_at or host.grant_expires_at != self.expires_at:
            raise ExecutionAuthorityResolutionError("Host control grant expired or disagrees")
        bound = self.registry.resolve_binding(host.host_app_id, host.namespace_id)
        if (
            bound is None
            or not bound.active
            or (bound.connector_id, bound.profile_revision)
            != (host.connector_id, host.connector_profile_revision)
        ):
            raise ExecutionAuthorityResolutionError("Host control connector changed")
        profile = self.registry.get_profile(
            host.host_app_id, bound.connector_id, bound.profile_revision
        )
        if profile is None or profile.profile_digest != host.connector_profile_digest:
            raise ExecutionAuthorityResolutionError("Host control profile changed")
        pinned = resolve_pinned_gateway(self.context, self.registry, self.credentials)
        if pinned is None or not pinned.shared_secret:
            raise ExecutionAuthorityResolutionError("Host control transport unavailable")
        manifest = HostToolManifest.from_payload(
            {
                "workloadIdentity": profile.workload_identity_ref,
                "bindingPolicy": "declared",
                "tools": [
                    {
                        "name": self.settings.tool_name,
                        "description": "Execution authority control",
                        "requiredArguments": list(_ARGUMENTS),
                        "argumentProperties": {
                            key: {"type": "string", "maxLength": 512} for key in _ARGUMENTS
                        },
                        "executionLocation": "host",
                        "scopes": [self.settings.required_scope],
                        "risk": "read",
                        "parallelSafe": False,
                        "idempotency": "none",
                        "resourceBindings": [],
                        "maxOutputBytes": 4096,
                        "timeoutSeconds": 2,
                    }
                ],
            }
        )
        owned = self.client is None
        client = self.client or httpx.Client(
            verify=HttpHostToolTransport._ssl_verify(), follow_redirects=False
        )
        try:
            pinned.transport = HttpHostToolTransport(
                client=client, deadline_monotonic=monotonic() + 2, max_response_bytes=8192
            )
            result = pinned.invoke(
                ToolCall(
                    tool_call_id=ToolCallId(UUID(self.binding.binding_digest[:32])),
                    created_at=now,
                    name=self.settings.tool_name,
                    arguments=self.arguments,
                ),
                self.context,
                manifest=manifest,
                idempotency_key="authority:" + self.binding.binding_digest,
            )
        finally:
            if owned:
                client.close()
        if result.status is not ToolCallStatus.EXECUTED:
            raise ExecutionAuthorityResolutionError("Host control refused or unavailable")
        response = HostAuthorityResponse.model_validate_json(result.output)
        identity = response.identity
        if any(
            not key or len(key) > 128 or not value or len(value) > 512
            for key, value in identity.items()
        ):
            raise ExecutionAuthorityResolutionError("Host control identity is invalid")
        expected = dict(self.expected_identity)
        for key in identity.keys() - expected.keys():
            resource = self.resource_identity.get(key)
            if not resource:
                raise ExecutionAuthorityResolutionError("Host control returned unbound identity")
            expected[key] = resource
        digest = sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if (
            identity != expected
            or response.metadata_digest != digest
            or self.metadata_digest not in (None, digest)
        ):
            raise ExecutionAuthorityResolutionError("Host control identity changed")
        if (
            response.expires_at.tzinfo is None
            or not datetime.now(UTC) < response.expires_at <= self.expires_at
        ):
            raise ExecutionAuthorityResolutionError("Host control expiry is invalid")
        self.metadata_digest = digest
        return response.expires_at
