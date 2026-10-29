"""Opt-in ERP control revalidation through the native, pinned Host Tool gateway.

This fixed probe is not a model tool and cannot execute business operations.
"""
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from time import monotonic
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field
from agent_core.application.execution_authority_replay import latest_authority_snapshot
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.execution_authority import (
    ExecutionAuthorityDecision, ExecutionAuthorityResolutionError,
    ExecutionAuthorityRevalidation, ExecutionAuthorityRevalidationRequest,
)
from agent_core.domain.task_bindings import TaskBindingSnapshot, require_task_host_context
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_integrations.host_credentials import ConfiguredHmacHostCredentialResolver
from agent_integrations.host_tools import HostToolManifest
from agent_integrations.host_tools.http import HttpHostToolTransport, _validate_endpoint
from zebra_agent_worker.bound_execution_authority import BoundHostExecutionAuthorityResolver
from zebra_agent_worker.host_gateway_resolution import resolve_pinned_gateway
from zebra_agent_worker.execution_errors import RetryableWorkerSetupError
from agent_integrations.host_tools.contracts import HostToolTransportError


class EarlyFreshRefusal(ExecutionAuthorityResolutionError):
    """Only the pre-private-read gate may emit this bounded permission decision."""

    code = "erp_fresh_authority_refused"

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(self.code)


class EarlyFreshUnavailable(RetryableWorkerSetupError):
    """Known external probe failure; native recovery retains its existing budget."""

    code = "erp_fresh_authority_unavailable"

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(self.code)


def require_early_authority(decision):
    if decision.reason in {"probe_timeout", "probe_network_unavailable", "probe_http_unavailable"}:
        raise EarlyFreshUnavailable(decision.reason)
    if decision.reason in {
        "grant_expired", "probe_expired", "prior_revocation", "host_identity_drift", "probe_rejected",
    }:
        raise EarlyFreshRefusal(decision.reason)
    return decision.require_allowed()


_ARGUMENTS = ("task_id", "thread_id", "run_id", "principal", "workspace_ref", "expires_at")
# Private singleton contract: no discovery, publication, capability expansion or business dispatch.
_MANIFEST = HostToolManifest.from_payload({
    "workloadIdentity": "erpnext-worker", "bindingPolicy": "declared", "tools": [{
        "name": "erpnext.authority", "description": "Revalidate ERP execution authority",
        "requiredArguments": list(_ARGUMENTS),
        "argumentProperties": {key: {"type": "string", "maxLength": 512} for key in _ARGUMENTS},
        "executionLocation": "host", "scopes": ["erpnext.read"], "risk": "read",
        "parallelSafe": False, "idempotency": "none", "resourceBindings": [],
        "maxOutputBytes": 4096, "timeoutSeconds": 2,
    }],
})


class ProbeIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    task_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=512)
    run_id: str = Field(min_length=1, max_length=512)
    principal: str = Field(min_length=1, max_length=512)
    workspace_ref: str = Field(min_length=1, max_length=512)
    company: str = Field(min_length=1, max_length=512)


class ProbeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    decision: str = Field(pattern="^allowed$")
    identity: ProbeIdentity
    metadata_digest: str = Field(pattern="^[0-9a-f]{64}$")
    expires_at: datetime


@dataclass(frozen=True)
class FreshDecision:
    decision: ExecutionAuthorityDecision
    expires_at: datetime | None
    reason: str

    def require_allowed(self) -> datetime:
        if self.decision is not ExecutionAuthorityDecision.ALLOWED or self.expires_at is None:
            raise ExecutionAuthorityResolutionError(f"ERP fresh authority: {self.reason}")
        return self.expires_at


def enabled(namespace: str | None) -> bool:
    value = os.environ.get("ZEBRA_ERPNEXT_FRESH_AUTHORITY", "disabled")
    if value not in {"disabled", "enabled"}:
        raise ValueError("invalid ERP fresh authority opt-in")
    if value == "enabled" and namespace != "erpnext":
        raise ValueError("ERP fresh authority requires the erpnext namespace")
    return value == "enabled"


def validate_wiring(namespace, loader, registry, settings):
    if not enabled(namespace):
        return False
    if not callable(loader) or registry is None or not settings.host_tool_shared_secret:
        raise ValueError("ERP fresh authority requires a binding loader, pinned profile and credential")
    bound = registry.resolve_binding("erpnext", "erpnext")
    profile = None if bound is None else registry.get_profile(bound.host_app_id, bound.connector_id, bound.profile_revision)
    if (profile is None or not bound.active or profile.status.value == "revoked"
            or profile.workload_identity_ref != "erpnext-worker"):
        raise ValueError("ERP fresh authority profile is missing or has the wrong workload")
    _validate_endpoint(profile.base_uri, resolver=None)
    return True


class FreshERPAuthority:
    def __init__(self, binding, registry, credentials, *, task_id, client=None):
        if not isinstance(binding, TaskBindingSnapshot):
            raise ExecutionAuthorityResolutionError("ERP fresh authority requires a typed stored binding")
        # Revalidate even a Pydantic object: model_copy/model_construct are not trust boundaries.
        self.binding = TaskBindingSnapshot.model_validate(binding.model_dump(mode="json"))
        self.registry, self.credentials = registry, credentials
        self.client = client
        self.task_id = str(task_id)
        self.context = self.binding.host_capability.host_context
        host = self.binding.host_capability
        if self.context is None or (host.host_app_id, host.namespace_id) != ("erpnext", "erpnext"):
            raise ExecutionAuthorityResolutionError("ERP fresh binding is outside its fixed namespace")
        self.thread = require_task_host_context(
            self.binding, self.context, task_id=self.task_id, now=datetime.now(UTC),
        )
        runs = [ref.resource_id for ref in self.context.resource_refs if ref.resource_type == "run"]
        principals = [ref.resource_id for ref in self.context.resource_refs if ref.resource_type == "principal"]
        if len(runs) != 1 or len(principals) != 1 or "erpnext.read" not in self.context.scopes:
            raise ExecutionAuthorityResolutionError("ERP fresh binding lacks a unique Run/principal/read scope")
        if host.grant_expires_at is None or host.grant_expires_at != self.context.expires_at:
            raise ExecutionAuthorityResolutionError("ERP fresh binding expiry disagrees")
        if not self.binding.effective_capabilities <= (host.capabilities & self.binding.agent_capability_ceiling.capabilities):
            raise ExecutionAuthorityResolutionError("ERP fresh binding expands capability ceilings")
        self.arguments = dict(task_id=self.task_id, thread_id=self.thread.resource_id, run_id=runs[0],
                              principal=principals[0], workspace_ref=self.context.workspace_ref,
                              expires_at=self.context.expires_at.isoformat())
        self._metadata_digest = None
        self._prior = None
        self._recorder = None
        self._denied = False

    @classmethod
    def for_execution(cls, service, session_id):
        if not service._erp_fresh_enabled:
            return None
        task_id = service._task_index_store.task_id_for_session(session_id)
        if task_id is None:
            raise ExecutionAuthorityResolutionError("ERP fresh authority requires indexed Task identity")
        return cls(service._task_binding_loader(session_id), service._egress_registry,
                   ConfiguredHmacHostCredentialResolver(service._settings.host_tool_shared_secret),
                   task_id=task_id)

    def probe(self, now: datetime) -> FreshDecision:
        if self._denied:
            return FreshDecision(ExecutionAuthorityDecision.REVOKED, None, "prior_revocation")
        if now >= self.context.expires_at:
            return FreshDecision(ExecutionAuthorityDecision.EXPIRED, None, "grant_expired")
        try:
            host = self.binding.host_capability
            bound = self.registry.resolve_binding("erpnext", "erpnext")
            if bound is None or not bound.active or (bound.connector_id, bound.profile_revision) != (host.connector_id, host.connector_profile_revision):
                return FreshDecision(ExecutionAuthorityDecision.REVOKED, None, "host_identity_drift")
            profile = self.registry.get_profile("erpnext", bound.connector_id, bound.profile_revision)
            if profile is None or profile.profile_digest != host.connector_profile_digest:
                return FreshDecision(ExecutionAuthorityDecision.REVOKED, None, "host_identity_drift")
            pinned = resolve_pinned_gateway(self.context, self.registry, self.credentials)
            if (pinned is None or pinned.endpoint != profile.base_uri
                    or pinned.workload_identity.subject != "erpnext-worker" or not pinned.shared_secret):
                raise ValueError("pinned probe unavailable")
            _validate_endpoint(pinned.endpoint, resolver=None)
            # Own only the client we create. Injected clients keep their configured CA/transport.
            owned = self.client is None
            client = self.client or httpx.Client(verify=HttpHostToolTransport._ssl_verify(), follow_redirects=False)
            try:
                transport = HttpHostToolTransport(client=client, deadline_monotonic=monotonic() + 2,
                                                 max_response_bytes=8192)
                request = transport.request
                network_failure = False

                def probe_request(*args, **kwargs):
                    nonlocal network_failure
                    try:
                        return request(*args, **kwargs)
                    except HostToolTransportError as error:
                        network_failure = isinstance(error.__cause__, (httpx.TimeoutException, httpx.NetworkError))
                        raise

                # ponytail: one private probe owns this transport; retain typed cause
                # before the generic gateway reduces it to a bounded reason string.
                transport.request = probe_request
                pinned.transport = transport
                key = "erp-authority:" + self.binding.binding_digest
                result = pinned.invoke(ToolCall(tool_call_id=UUID(self.binding.binding_digest[:32]), created_at=now, name="erpnext.authority", arguments=self.arguments),
                                       self.context, manifest=_MANIFEST, idempotency_key=key)
            finally:
                if owned:
                    client.close()
            if result.status is not ToolCallStatus.EXECUTED:
                reason = result.metadata.get("reason")
                status = result.metadata.get("http_status")
                if reason == "timeout":
                    code = "probe_timeout"
                elif network_failure:
                    code = "probe_network_unavailable"
                elif reason == "host_http_error" and type(status) is int and status in {401, 403}:
                    code = "probe_rejected"
                elif reason == "host_http_error" and type(status) is int and (
                    status in {408, 425, 429, 500, 502, 503, 504}
                ):
                    code = "probe_http_unavailable"
                else:
                    code = "probe_unavailable"
                return FreshDecision(ExecutionAuthorityDecision.DENIED, None, code)
            response = ProbeResponse.model_validate_json(result.output)
            identity = response.identity.model_dump()
            from agent_storage.postgres.erp_chat_readonly import enabled as chat_enabled
            if chat_enabled(self.context.namespace_id):
                companies = [r.resource_id for r in self.context.resource_refs if r.resource_type == 'company']
                if companies != [identity['company']]:
                    return FreshDecision(ExecutionAuthorityDecision.REVOKED, None, 'host_identity_drift')
            digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if (any(identity[key] != value for key, value in self.arguments.items() if key != "expires_at")
                    or digest != response.metadata_digest
                    or (self._metadata_digest is not None and digest != self._metadata_digest)):
                return FreshDecision(ExecutionAuthorityDecision.REVOKED, None, "host_identity_drift")
            if response.expires_at.tzinfo is None or response.expires_at > self.context.expires_at:
                return FreshDecision(ExecutionAuthorityDecision.DENIED, None, "probe_expiry_invalid")
            if response.expires_at <= datetime.now(UTC):
                return FreshDecision(ExecutionAuthorityDecision.EXPIRED, None, "probe_expired")
            self._metadata_digest = digest
            return FreshDecision(ExecutionAuthorityDecision.ALLOWED, response.expires_at, "allowed")
        except Exception:
            # Exceptions contain transport/credential details; only bounded reason codes are durable.
            return FreshDecision(ExecutionAuthorityDecision.DENIED, None, "probe_unavailable")

    def bind_recorder(self, recorder: Callable, events):
        self._recorder = recorder
        self._prior = latest_authority_snapshot(events)
        if self._prior is None:
            raise ExecutionAuthorityResolutionError("ERP fresh boundary has no durable authority snapshot")

    def check(self, boundary: str, identity: str = ""):
        if self._recorder is None:
            raise ExecutionAuthorityResolutionError("ERP fresh journal is not bound")
        recorder = self._recorder()
        # One per-recorder RLock owns prior -> probe -> append. Business I/O happens after release.
        with recorder.mutation():
            recorder.require_active_execution()
            prior = self._prior
            resolver = BoundHostExecutionAuthorityResolver(self.binding, fresh_checker=self.probe)
            decision = resolver.revalidate_attempt(ExecutionAuthorityRevalidationRequest(
                session_id=recorder.session.session_id, attempt_number=prior.attempt_number,
                scope=prior.scope, prior_snapshot=prior, validated_at=datetime.now(UTC),
            ))
            decision = decision.model_copy(update={"reason_code": f"erp_fresh:{boundary}:{identity}:{decision.reason_code or 'allowed'}"[:256]})
            recorder.append(EventType.EXECUTION_AUTHORITY_REVALIDATED, EventActor.SYSTEM, decision.to_event_payload())
            if decision.effective_snapshot is not None:
                self._prior = decision.effective_snapshot
            if decision.decision not in {ExecutionAuthorityDecision.ALLOWED, ExecutionAuthorityDecision.NARROWED}:
                self._denied = True
                raise ExecutionAuthorityResolutionError("ERP fresh authority denied execution")

    def model(self, gateway):
        # These native adapters invoke this hook before EACH transport attempt, outside retry catches.
        if not hasattr(gateway, "authority_check"):
            raise ExecutionAuthorityResolutionError("ERP fresh model adapter has no retry authority seam")
        gateway.authority_check = lambda request_id: self.check("model", request_id)
        return gateway
