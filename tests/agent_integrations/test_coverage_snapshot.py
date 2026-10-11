"""Actual Trench coverage wire over the existing signed gateway and real SQLite."""

import base64
import copy
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import RLock
from uuid import uuid4

import pytest
from agent_core.domain.coverage_contracts import (
    CoverageContract,
    CoverageRefusedError,
    coverage_digest,
)
from agent_core.domain.coverage_persistence import coverage_manifest_bytes
from agent_core.domain.coverage_snapshot import CoveragePageRequest, CoverageRecord
from agent_core.domain.coverage_validation import manifest_digest
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import SessionId
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_integrations.coverage_snapshot import HostCoverageSnapshotAdapter
from agent_integrations.host_tools.contracts import (
    HostToolManifest,
    HostToolTransportResponse,
    HostWorkloadIdentity,
)
from agent_integrations.host_tools.gateway import HostToolGateway
from agent_storage.artifact_payloads import SQLiteArtifactPayloadStore

NOW = datetime.now(UTC)
CONTRACT = CoverageContract.model_validate(
    {
        "scope": {
            "timezone": "Asia/Shanghai",
            "from_inclusive": "2026-01-01T00:00:00Z",
            "to_exclusive": "2026-02-01T00:00:00Z",
        },
        "checks": [
            {"id": "check", "version": "1", "kind": "program", "definition_digest": "a" * 64}
        ],
    }
)
AUTHORITY = HostContextEnvelope.model_validate(
    {
        "grant_id": "grant",
        "host_app_id": "trench",
        "namespace_id": "ns",
        "workspace_ref": "workspace",
        "resource_refs": [{"type": "trench.history", "id": "history"}],
        "scopes": ["history.read", "history.snapshot.write"],
        "limits": {
            "max_runtime_seconds": 60,
            "max_model_tokens": 100,
            "max_artifact_bytes": 33554432,
        },
        "origin": "https://trench.example",
        "policy_version": "1",
        "expires_at": NOW + timedelta(hours=1),
    }
)


def frozen_manifest():
    return HostToolManifest.from_payload(
        {
            "workloadIdentity": "worker",
            "tools": [
                {
                    "name": "dataset.snapshot." + name,
                    "executionLocation": "host",
                    "scopes": [
                        "history.read",
                        *(["history.snapshot.write"] if name == "create" else []),
                    ],
                    "risk": "write" if name == "create" else "read",
                    "idempotency": "required" if name == "create" else "none",
                    "maxOutputBytes": 131072,
                    "resourceBindings": [
                        {"argumentPointer": "/history_ref", "resourceType": "trench.history"}
                    ],
                }
                for name in ("create", "get", "page", "read")
            ],
        }
    )


class HostWire:
    def __init__(self, bodies):
        self.bodies = bodies
        self.records = tuple(
            CoverageRecord.model_validate(
                {
                    "ordinal": i,
                    "record_id": f"r{i}",
                    "content_digest": coverage_digest({"event": i}),
                    "parts": [
                        {
                            "id": "canonical_body",
                            "digest": sha256(body).hexdigest(),
                            "byte_length": len(body),
                        }
                    ],
                }
            )
            for i, body in enumerate(bodies)
        )
        self.calls = []
        self.mutate = lambda name, value: value
        self.short = False
        self.revoked = False

    def request(self, method, url, *, headers, body, timeout_seconds):
        assert method == "POST" and headers["X-Zebra-Host-Auth"]
        name = body["toolName"].rsplit(".", 1)[1]
        args = body["arguments"]
        assert args["history_ref"] == "history"
        self.calls.append(body)
        if self.revoked:
            return HostToolTransportResponse(403, {"error": "authority_invalid"})
        descriptor = {
            "schema_version": 1,
            "state": "sealed",
            "namespace": "ns",
            "host_id": "trench",
            "snapshot_id": "snapshot",
            "authority_revision": "b" * 64,
            "contract_digest": CONTRACT.digest,
            "scope_digest": CONTRACT.scope.digest,
            "manifest_digest": manifest_digest(CONTRACT, self.records),
            "record_count": len(self.records),
            "as_of": (NOW - timedelta(seconds=1)).isoformat(),
            "expires_at": (NOW + timedelta(minutes=30)).isoformat(),
        }
        if name in {"get", "create"}:
            value = {
                "status": "ready",
                "snapshot": descriptor,
                "scope": CONTRACT.scope.model_dump(mode="json"),
                "sealed_at": NOW.isoformat(),
                "content_capabilities": ["canonical_body"],
                "provenance": {
                    "dataset": "trench.subscribed_events",
                    "history_ref": "history",
                    "workspace_ref": "workspace",
                    "period_count": 0,
                    "periods_digest": "b" * 64,
                },
            }
        elif name == "page":
            start = int(args.get("cursor") or 0)
            end = min(start + (1 if self.short else args["page_size"]), len(self.records))
            value = {
                "status": "ready",
                "namespace": "ns",
                "snapshot_id": "snapshot",
                "scope_digest": CONTRACT.scope.digest,
                "records": [r.model_dump(mode="json") for r in self.records[start:end]],
                "next_cursor": str(end) if end < len(self.records) else None,
                "provenance": {r.record_id: {"title": "中文"} for r in self.records[start:end]},
            }
            value["page_digest"] = coverage_digest(value)
        else:
            index = int(args["record_id"][1:])
            data = self.bodies[index]
            offset = args["offset"]
            end = min(offset + args["max_bytes"], len(data))
            value = {
                "status": "ready",
                "namespace": "ns",
                "snapshot_id": "snapshot",
                "record_id": f"r{index}",
                "content_digest": self.records[index].content_digest,
                "data_base64": base64.b64encode(data[offset:end]).decode(),
                "offset": offset,
                "byte_length": len(data),
                "digest": sha256(data).hexdigest(),
                "next_offset": end if end < len(data) else None,
            }
        value = self.mutate(name, copy.deepcopy(value))
        result = {"output": json.dumps(value, ensure_ascii=False)}
        return HostToolTransportResponse(200, result)


def setup_adapter(tmp_path, bodies=(b"hello",), **kwargs):
    host = HostWire(bodies)
    store = SQLiteArtifactPayloadStore(tmp_path / "artifacts.sqlite")
    manifest = frozen_manifest()
    gateway = HostToolGateway(
        "https://trench.example",
        HostWorkloadIdentity("worker", "ns", "trench"),
        shared_secret="fixture-secret",
        transport=host,
    )

    def admitted_effect(call, context, *, idempotency_key, required_resource, manifest):
        # Explicit test capability stands in for admission. Trench's current wrapper
        # has no Host Effect receipt; production composition must resolve that boundary.
        assert context == AUTHORITY and required_resource.resource_id == "history"
        assert manifest.digest == frozen_manifest().digest
        response = host.request(
            "POST",
            "https://trench.example/tools/create/invoke",
            headers={"X-Zebra-Host-Auth": "admitted-fixture"},
            body={
                "toolName": call.name,
                "arguments": call.arguments,
                "idempotencyKey": idempotency_key,
            },
            timeout_seconds=30,
        )
        return ToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=response.body["output"],
        )

    options = dict(
        session_id=SessionId(uuid4()),
        authority=AUTHORITY,
        history_ref="history",
        manifest=manifest,
        invoke=gateway.invoke,
        admitted_effect_invoke=admitted_effect,
        artifacts=store,
        publication_lock=RLock(),
    )
    options.update(kwargs)
    return HostCoverageSnapshotAdapter(**options), host, store, options


def test_durable_retry_short_pages_two_digests_and_unicode(tmp_path):
    adapter, host, store, options = setup_adapter(tmp_path, (("汉" * 22000).encode(), b"two"))
    host.short = True
    snapshot = adapter.create(CONTRACT, authority=AUTHORITY, idempotency_key=" effect-key ")
    assert host.calls[0]["idempotencyKey"] == " effect-key "
    assert "manifest_artifact_ref" not in host.mutate("get", {"snapshot": {}})["snapshot"]
    stored = next(store.get_payload(a) for a in [adapter.manifest_artifact_id(snapshot)])
    assert stored.sha256 == sha256(coverage_manifest_bytes(host.records)).hexdigest()
    assert stored.sha256 != snapshot.manifest_digest
    fresh = HostCoverageSnapshotAdapter(
        **{**options, "artifacts": SQLiteArtifactPayloadStore(tmp_path / "artifacts.sqlite")}
    )
    before = len(host.calls)
    assert fresh.get("snapshot", authority=AUTHORITY) == snapshot
    read = fresh.read(snapshot, host.records[0], host.records[0].parts[0], authority=AUTHORITY)
    assert not any(c["toolName"].endswith("page") for c in host.calls[before:])
    assert (
        store.read_payload_bytes(
            fresh.body_artifact_id(snapshot, host.records[0], host.records[0].parts[0])
        )
        == host.bodies[0]
    )
    assert read.artifact_ref.startswith("artifact://")
    assert adapter.create(CONTRACT, authority=AUTHORITY, idempotency_key=" effect-key ") == snapshot
    host.revoked = True
    with pytest.raises(CoverageRefusedError):
        fresh.read(snapshot, host.records[0], host.records[0].parts[0], authority=AUTHORITY)


def test_empty_and_page(tmp_path):
    adapter, host, _, _ = setup_adapter(tmp_path, ())
    snapshot = adapter.get("snapshot", authority=AUTHORITY)
    assert snapshot.record_count == 0
    page = adapter.page(
        CoveragePageRequest(
            namespace="ns",
            snapshot_id="snapshot",
            scope_digest=CONTRACT.scope.digest,
            page_size=100,
        ),
        authority=AUTHORITY,
    )
    assert page.records == () and page.next_cursor is None


def test_missing_effect_capability(tmp_path):
    adapter, host, _, _ = setup_adapter(tmp_path, admitted_effect_invoke=None)
    with pytest.raises(CoverageRefusedError, match="coverage_unsupported"):
        adapter.create(CONTRACT, authority=AUTHORITY, idempotency_key="key")
    assert not host.calls
