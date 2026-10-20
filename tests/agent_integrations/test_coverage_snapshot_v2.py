"""Neutral immutable source v2, with real gateway and SQLite Artifact proofs."""

import copy
import json
from datetime import timedelta
from threading import RLock
from uuid import uuid4

import pytest
from agent_core.domain.coverage_contracts import (
    CoverageContract,
    CoverageRefusedError,
    coverage_digest,
)
from agent_core.domain.coverage_task_admission import CoverageTaskAdmission
from agent_core.domain.host_authority import HostContextEnvelope, HostResourceRef
from agent_core.domain.identifiers import SessionId
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_integrations.coverage_snapshot import HostCoverageSnapshotAdapter
from agent_integrations.host_tools.contracts import HostToolManifest, HostWorkloadIdentity
from agent_integrations.host_tools.gateway import HostToolGateway
from agent_storage.artifact_payloads import SQLiteArtifactPayloadStore

from tests.agent_integrations.test_coverage_snapshot import AUTHORITY, CONTRACT, NOW, HostWire

V2_SOURCE = HostResourceRef(type="archive.collection", id="collection")
V2_CONTRACT = CoverageContract.model_validate(
    {
        **CONTRACT.model_dump(mode="json"),
        "schema_version": 2,
        "dataset": "archive.documents",
        "dataset_revision": "revision-7",
        "source": {
            "protocol": "coverage-source/2",
            "resource_type": "archive.collection",
            "read_scope": "collection.read",
            "create_scope": "collection.snapshot.create",
        },
        "scope": {"selection_ref": "opaque-selection", "selection_digest": "c" * 64},
    }
)
V2_AUTHORITY = HostContextEnvelope.model_validate(
    {
        **AUTHORITY.model_dump(),
        "host_app_id": "archive",
        "origin": "https://archive.example",
        "resource_refs": [V2_SOURCE],
        "scopes": ["collection.read", "collection.snapshot.create"],
    }
)


def manifest_v2():
    return HostToolManifest.from_payload(
        {
            "workloadIdentity": "worker",
            "bindingPolicy": "declared",
            "tools": [
                {
                    "name": "dataset.snapshot." + name,
                    "executionLocation": "host",
                    "scopes": [
                        "collection.read",
                        *(["collection.snapshot.create"] if name == "create" else []),
                    ],
                    "risk": "write" if name == "create" else "read",
                    "idempotency": "required" if name == "create" else "none",
                    "maxOutputBytes": 131072,
                    "resourceBindings": [
                        {"argumentPointer": "/source_ref", "resourceType": "archive.collection"}
                    ],
                }
                for name in ("create", "get", "page", "read")
            ],
        }
    )


class NeutralWire(HostWire):
    def __init__(self, bodies, *, contract=V2_CONTRACT, authority=V2_AUTHORITY):
        super().__init__(bodies)
        self.contract = contract
        self.authority = authority

    def request(self, method, url, *, headers, body, timeout_seconds):
        assert body["arguments"]["source_ref"] == "collection"
        legacy_body = copy.deepcopy(body)
        legacy_body["arguments"].pop("source_ref")
        legacy_body["arguments"]["history_ref"] = "history"
        mutation = self.mutate
        self.mutate = lambda name, value: value
        try:
            response = super().request(
                method, url, headers=headers, body=legacy_body, timeout_seconds=timeout_seconds
            )
        finally:
            self.mutate = mutation
        if self.revoked:
            return response
        value = json.loads(response.body["output"])
        name = body["toolName"].rsplit(".", 1)[1]
        if name in {"create", "get"}:
            value["schema_version"] = 2
            value["scope"] = self.contract.scope.model_dump(mode="json")
            value["snapshot"].update(
                host_id=self.authority.host_app_id,
                contract_digest=self.contract.digest,
                scope_digest=self.contract.scope.digest,
            )
            from agent_integrations.coverage_snapshot_wire import host_manifest_digest

            value["snapshot"]["manifest_digest"] = host_manifest_digest(
                self.contract.scope.digest, self.records
            )
            value["provenance"] = {
                "dataset": self.contract.dataset,
                "dataset_revision": self.contract.dataset_revision,
                "resource_ref": V2_SOURCE.model_dump(by_alias=True),
                "workspace_ref": self.authority.workspace_ref,
                "authority_revision": "b" * 64,
            }
        elif name == "page":
            value["scope_digest"] = self.contract.scope.digest
            value["page_digest"] = coverage_digest(
                {k: v for k, v in value.items() if k != "page_digest"}
            )
        return type(response)(200, {"output": json.dumps(mutation(name, value))})


def setup_v2(tmp_path, bodies=(b"neutral body",)):
    wire = NeutralWire(bodies)
    manifest = manifest_v2()
    gateway = HostToolGateway(
        "https://archive.example",
        HostWorkloadIdentity("worker", "ns", "archive"),
        shared_secret="fixture-secret",
        transport=wire,
    )

    def effect(call, context, **kwargs):
        response = wire.request(
            "POST",
            "https://archive.example",
            headers={"X-Zebra-Host-Auth": "effect"},
            body={"toolName": call.name, "arguments": call.arguments},
            timeout_seconds=30,
        )
        return ToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=response.body["output"],
        )

    adapter = HostCoverageSnapshotAdapter(
        session_id=SessionId(uuid4()),
        authority=V2_AUTHORITY,
        source_ref=V2_SOURCE,
        contract=V2_CONTRACT,
        manifest=manifest,
        invoke=gateway.invoke,
        admitted_effect_invoke=effect,
        artifacts=SQLiteArtifactPayloadStore(tmp_path / "neutral.sqlite"),
        publication_lock=RLock(),
        now=lambda: NOW,
    )
    return adapter, wire, V2_AUTHORITY, V2_CONTRACT


@pytest.mark.parametrize("bodies", [(), (b"first",), (b"first", b"second")])
def test_complete_and_prepared_restore(tmp_path, bodies):
    adapter, wire, authority, contract = setup_v2(tmp_path, bodies)
    snapshot = adapter.create(contract, authority=authority, idempotency_key="create")
    assert snapshot.host_id == "archive" and snapshot.source_resource_ref == "collection"
    prepared = adapter.prepare(snapshot.snapshot_id, authority=authority)
    for row in prepared.records:
        assert prepared.read(row, row.parts[0]).artifact_ref
    assert adapter.get(snapshot.snapshot_id, authority=authority) == snapshot
    wire.revoked = True
    with pytest.raises(CoverageRefusedError):
        adapter.get(snapshot.snapshot_id, authority=authority)


@pytest.mark.parametrize(
    "failure",
    [
        "dataset",
        "revision",
        "resource",
        "scope",
        "contract",
        "downgrade",
        "expired",
        "proof",
        "partial",
    ],
)
def test_all_restored_descriptor_and_manifest_paths_fail_closed(tmp_path, failure):
    adapter, wire, authority, contract = setup_v2(tmp_path)
    snapshot = adapter.create(contract, authority=authority, idempotency_key="create")
    prepared = adapter.prepare(snapshot.snapshot_id, authority=authority)

    def mutate(name, value):
        if name == "get":
            if failure == "dataset":
                value["provenance"]["dataset"] = "other"
            elif failure == "revision":
                value["provenance"]["dataset_revision"] = "other"
            elif failure == "resource":
                value["provenance"]["resource_ref"]["type"] = "other"
            elif failure == "scope":
                value["scope"]["selection_ref"] = "other"
            elif failure == "contract":
                value["snapshot"]["contract_digest"] = "d" * 64
            elif failure == "downgrade":
                value.pop("schema_version")
            elif failure == "expired":
                value["snapshot"]["expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
        if name == "read" and failure == "proof":
            value["digest"] = "d" * 64
        if name == "page" and failure == "partial":
            value["records"] = []
            value["provenance"] = {}
            value["page_digest"] = coverage_digest(
                {k: v for k, v in value.items() if k != "page_digest"}
            )
        return value

    wire.mutate = mutate
    with pytest.raises(CoverageRefusedError):
        if failure == "partial":
            adapter.artifacts.store = SQLiteArtifactPayloadStore(tmp_path / "empty.sqlite")
            adapter.get(snapshot.snapshot_id, authority=authority)
        else:
            prepared.read(prepared.records[0], prepared.records[0].parts[0])


def test_legacy_golden_and_v1_version_boundary():
    from tests.agent_core.test_coverage_legacy_golden import GOLDEN

    golden = GOLDEN
    contract = CoverageContract.model_validate(golden["contract"])
    assert contract.model_dump(mode="json") == golden["contract"]
    assert contract.digest == golden["contract_digest"]
    assert (
        CoverageTaskAdmission.model_validate(golden["admission"]).model_dump(mode="json")
        == golden["admission"]
    )
    for change in ({"dataset": "other"}, {"dataset_revision": "x"}, {"schema_version": 2}):
        with pytest.raises(ValueError):
            CoverageContract.model_validate({**golden["contract"], **change})
    missing = V2_CONTRACT.model_dump(mode="json")
    missing.pop("dataset")
    with pytest.raises(ValueError):
        CoverageContract.model_validate(missing)


@pytest.mark.parametrize("name", ["create", "get", "page", "read"])
def test_manifest_cannot_be_weakened_or_resource_overridden(tmp_path, name):
    adapter, _, authority, _ = setup_v2(tmp_path)
    host = adapter.host
    with pytest.raises(CoverageRefusedError):
        host.call(
            name,
            {"source_ref": {"type": "archive.collection", "id": "other"}},
            authority,
            host.budget(authority),
            "key" if name == "create" else None,
        )
    payload = manifest_v2().to_payload()
    payload.pop("manifestDigest")
    for entry in payload["tools"]:
        if entry["name"] == "dataset.snapshot." + name:
            entry["scopes"] = ["weak.read"]
    host.manifest = HostToolManifest.from_payload(payload)
    weaker = authority.model_copy(update={"scopes": (*authority.scopes, "weak.read")})
    with pytest.raises(CoverageRefusedError):
        host.call(name, {}, weaker, host.budget(weaker), "key" if name == "create" else None)


def test_v2_source_requires_frozen_contract_for_create(tmp_path):
    from agent_integrations.coverage_snapshot_source import HostCoverageSnapshotSource

    with pytest.raises(ValueError):
        HostCoverageSnapshotSource(
            session_id=SessionId(uuid4()),
            authority=V2_AUTHORITY,
            source_ref=V2_SOURCE,
            manifest=manifest_v2(),
            invoke=None,
        )
    adapter, _, authority, contract = setup_v2(tmp_path)
    changed = CoverageContract.model_validate(
        {**contract.model_dump(), "dataset_revision": "other"}
    )
    with pytest.raises(CoverageRefusedError):
        adapter.create(changed, authority=authority, idempotency_key="key")


def test_v2_body_read_requires_source_identity_even_with_cached_manifest(tmp_path):
    adapter, _, authority, contract = setup_v2(tmp_path)
    snapshot = adapter.create(contract, authority=authority, idempotency_key="key")
    prepared = adapter.prepare(snapshot.snapshot_id, authority=authority)
    with pytest.raises(CoverageRefusedError):
        adapter.read(
            snapshot.model_copy(update={"source_resource_ref": None}),
            prepared.records[0],
            prepared.records[0].parts[0],
            authority=authority,
        )


@pytest.mark.parametrize("name", ["create", "get", "page", "read"])
def test_v2_manifest_additional_resource_binding_is_refused_before_invoke(tmp_path, name):
    adapter, wire, authority, _ = setup_v2(tmp_path)
    payload = manifest_v2().to_payload()
    payload.pop("manifestDigest")
    for entry in payload["tools"]:
        if entry["name"] == "dataset.snapshot." + name:
            entry["resourceBindings"].append(
                {"argumentPointer": "/other", "resourceType": "archive.other"}
            )
    adapter.host.manifest = HostToolManifest.from_payload(payload)
    with pytest.raises(CoverageRefusedError) as refused:
        adapter.host.call(
            name, {}, authority, adapter.host.budget(authority), "key" if name == "create" else None
        )
    assert refused.value.reason.value == "coverage_unsupported"
    assert not wire.calls
