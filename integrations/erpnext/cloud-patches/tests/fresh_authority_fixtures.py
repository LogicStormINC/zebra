"""Run on pinned105 + overlay_imports; no database, real model or external network."""

import importlib as importlib

import overlay_imports as overlay_imports

# isort: split
import ast as ast
import hashlib as hashlib
import hmac as hmac
import inspect as inspect
import json as json
import os as os
import sys as sys
from concurrent.futures import ThreadPoolExecutor as ThreadPoolExecutor
from contextlib import contextmanager as contextmanager
from datetime import UTC as UTC
from datetime import datetime as datetime
from datetime import timedelta as timedelta
from pathlib import Path as Path
from threading import RLock as RLock
from types import ModuleType as ModuleType
from types import SimpleNamespace as NS
from unittest.mock import Mock as Mock
from unittest.mock import patch as patch
from uuid import UUID as UUID
from uuid import uuid4 as uuid4
from zoneinfo import ZoneInfo as ZoneInfo

import httpx as httpx
from agent_core.domain.agent_capabilities import capability_set as capability_set
from agent_core.domain.events import EventActor as EventActor
from agent_core.domain.events import EventType as EventType
from agent_core.domain.events import SessionEvent as SessionEvent
from agent_core.domain.execution_authority import (
    ExecutionAuthorityResolutionError as ExecutionAuthorityResolutionError,
)
from agent_core.domain.execution_authority import (
    ExecutionAuthorityResolutionRequest as ExecutionAuthorityResolutionRequest,
)
from agent_core.domain.execution_authority import (
    ExecutionAuthorityRevalidation as ExecutionAuthorityRevalidation,
)
from agent_core.domain.host_authority import HostContextEnvelope as HostContextEnvelope
from agent_core.domain.host_authority import HostResourceRef as HostResourceRef
from agent_core.domain.host_authority import HostTechnicalLimits as HostTechnicalLimits
from agent_core.domain.host_connectors import HostConnectorBinding as HostConnectorBinding
from agent_core.domain.host_connectors import (
    HostConnectorProfileVersion as HostConnectorProfileVersion,
)
from agent_core.domain.task_bindings import (
    AgentCapabilityCeilingSnapshot as AgentCapabilityCeilingSnapshot,
)
from agent_core.domain.task_bindings import HostCapabilitySnapshot as HostCapabilitySnapshot
from agent_core.domain.task_bindings import TaskBindingSnapshot as TaskBindingSnapshot
from agent_core.domain.task_bindings import host_context_digest as host_context_digest
from agent_core.domain.tools import ToolCall as ToolCall
from agent_integrations.host_credentials import (
    ConfiguredHmacHostCredentialResolver as ConfiguredHmacHostCredentialResolver,
)
from agent_integrations.openai_compatible import (
    OpenAICompatibleModelGateway as OpenAICompatibleModelGateway,
)
from zebra_agent_worker import erp_fresh_authority as fresh
from zebra_agent_worker.bound_execution_authority import (
    BoundHostExecutionAuthorityResolver as BoundHostExecutionAuthorityResolver,
)
from zebra_agent_worker.bound_execution_authority import (
    select_attempt_authority as select_attempt_authority,
)
from zebra_agent_worker.worker_tool_gateway import WorkerToolGateway as WorkerToolGateway

NOW = datetime.now(UTC)
SID, TASK, RUN = uuid4(), str(uuid4()), str(uuid4())
PROFILE = HostConnectorProfileVersion(
    host_app_id="erpnext",
    connector_id="erp",
    profile_revision=1,
    base_uri="https://erp.example.test",
    manifest_path="/manifest",
    invoke_path_template="/tools",
    supported_protocol_versions=("v1",),
    workload_identity_ref="erpnext-worker",
    credential_ref="erp/workload",
)
PROFILE_BINDING = HostConnectorBinding(
    host_app_id="erpnext",
    namespace_id="erpnext",
    connector_id="erp",
    profile_revision=1,
    binding_revision=1,
)
REGISTRY = NS(resolve_binding=lambda *a: PROFILE_BINDING, get_profile=lambda *a: PROFILE)
CAPS = capability_set(["agent.execute", "evidence.read"])
CONTEXT = HostContextEnvelope(
    grant_id="check-only-grant",
    host_app_id="erpnext",
    namespace_id="erpnext",
    workspace_ref="erp-u-" + "a" * 40,
    resource_refs=tuple(
        HostResourceRef(type=k, id=v)
        for k, v in (("thread", "host-thread"), ("principal", "qa-user"), ("run", RUN))
    ),
    scopes=("agent.run", "erpnext.read"),
    limits=HostTechnicalLimits(
        max_runtime_seconds=600, max_model_tokens=40000, max_artifact_bytes=1000
    ),
    origin="https://erp.example.test",
    policy_version="erpnext-v1",
    expires_at=NOW + timedelta(minutes=10),
)
HOST = HostCapabilitySnapshot(
    host_app_id="erpnext",
    authority_issuer="https://erp.example.test",
    namespace_id="erpnext",
    grant_digest=host_context_digest(CONTEXT),
    host_context=CONTEXT,
    grant_expires_at=CONTEXT.expires_at,
    connector_id="erp",
    connector_profile_revision=1,
    connector_profile_digest=PROFILE.profile_digest,
    manifest_digest="a" * 64,
    capabilities=CAPS,
    resource_binding_digest="b" * 64,
    bound_at=NOW,
)
BINDING = TaskBindingSnapshot(
    task_id=TASK,
    agent_capability_ceiling=AgentCapabilityCeilingSnapshot(
        definition_snapshot_digest="c" * 64,
        capability_profile_ref="test/default@1",
        capabilities=CAPS,
        resolved_at=NOW,
    ),
    host_capability=HOST,
    zebra_policy_digest="d" * 64,
    effective_capabilities=CAPS,
    binding_revision=1,
    bound_at=NOW,
)
CREDENTIAL = ConfiguredHmacHostCredentialResolver("test-only-hmac")


class Host:
    def __init__(self):
        self.mode, self.calls = "allow", []

    def __call__(self, request):
        body = json.loads(request.content)
        self.calls.append(body)
        assert request.url.path == "/tools/erpnext.authority/invoke"
        assert body["toolName"] == "erpnext.authority" and set(body["arguments"]) == set(
            fresh._ARGUMENTS
        )
        canonical = "\n".join(
            [
                "POST",
                request.url.path,
                CONTEXT.grant_id,
                CONTEXT.workspace_ref,
                "erpnext",
                "erpnext",
                json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ]
        )
        assert hmac.compare_digest(
            request.headers["X-Zebra-Host-Auth"],
            hmac.new(b"test-only-hmac", canonical.encode(), hashlib.sha256).hexdigest(),
        )
        assert request.headers["X-Zebra-Workload-Identity"] == "erpnext-worker"
        if self.mode == "timeout":
            raise httpx.ReadTimeout("test timeout")
        if self.mode == "revoke":
            return httpx.Response(403, json={"error": "permission revoked"})
        if self.mode == "malformed":
            return httpx.Response(200, json={"output": '{"decision": "allowed"}'})
        identity = {
            key: value for key, value in body["arguments"].items() if key != "expires_at"
        } | {"company": "QA Company"}
        if self.mode == "drift":
            identity["run_id"] = "different-run"
        expiry = CONTEXT.expires_at
        if self.mode == "expand":
            expiry += timedelta(seconds=1)
        if self.mode == "expired":
            expiry = NOW - timedelta(seconds=1)
        result = dict(
            decision="allowed",
            identity=identity,
            metadata_digest=hashlib.sha256(
                json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            expires_at=expiry.isoformat(),
        )
        return httpx.Response(200, json={"output": json.dumps(result)})


class Recorder:
    def __init__(self, snapshot):
        self.lock = RLock()
        self.session = NS(session_id=SID)
        self.events = []
        self.active = True
        self.snapshot = snapshot

    @contextmanager
    def mutation(self):
        with self.lock:
            yield

    def require_active_execution(self):
        assert self.active, "lease/control lost"

    def append(self, event_type, actor, payload):
        with self.lock:
            assert event_type is EventType.EXECUTION_AUTHORITY_REVALIDATED
            item = ExecutionAuthorityRevalidation.model_validate(payload)
            assert item.prior_snapshot_digest == self.snapshot.snapshot_digest
            if item.effective_snapshot is not None:
                self.snapshot.ensure_not_expanded(item.effective_snapshot)
                self.snapshot = item.effective_snapshot
            self.events.append(item)


def guard(host=None):
    host = host or Host()
    gate = fresh.FreshERPAuthority(
        BINDING,
        REGISTRY,
        CREDENTIAL,
        task_id=TASK,
        client=httpx.Client(transport=httpx.MockTransport(host)),
    )
    snapshot = BoundHostExecutionAuthorityResolver(BINDING).resolve_for_attempt(
        ExecutionAuthorityResolutionRequest(
            session_id=SID,
            attempt_number=1,
            scope=BoundHostExecutionAuthorityResolver(BINDING).scope,
            validated_at=NOW,
        )
    )
    recorder = Recorder(snapshot)
    event = SessionEvent.create(
        session_id=SID,
        sequence=1,
        event_type=EventType.EXECUTION_AUTHORITY_RESOLVED,
        actor=EventActor.SYSTEM,
        payload=snapshot.to_event_payload(),
        created_at=NOW,
    )
    gate.bind_recorder(lambda: recorder, [event])
    return gate, host, recorder


def refused(call):
    try:
        call()
    except ExecutionAuthorityResolutionError:
        pass
    else:
        raise AssertionError("revoked boundary dispatched")
