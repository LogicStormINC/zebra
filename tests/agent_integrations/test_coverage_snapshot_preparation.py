"""Artifact-free source intent and shared legacy verification regressions."""

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from threading import RLock
from uuid import uuid4

import pytest
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_core.domain.coverage_persistence import coverage_manifest_bytes
from agent_core.domain.coverage_snapshot import CoverageSnapshot
from agent_core.domain.host_authority import HostResourceRef
from agent_core.domain.identifiers import SessionId
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_integrations.coverage_snapshot import HostCoverageSnapshotAdapter
from agent_integrations.coverage_snapshot_source import HostCoverageSnapshotSource
from agent_integrations.coverage_snapshot_wire import verify_manifest
from agent_integrations.host_tools.contracts import HostWorkloadIdentity
from agent_integrations.host_tools.gateway import HostToolGateway
from agent_storage.artifact_payloads import SQLiteArtifactPayloadStore

from tests.agent_integrations.test_coverage_snapshot import (
    AUTHORITY,
    CONTRACT,
    NOW,
    HostWire,
    frozen_manifest,
)
from tests.agent_integrations.test_coverage_snapshot_refusals import rewrite_page


def setup_source(bodies=(b"hello",), **kwargs):
    host = HostWire(bodies, now=kwargs.get("now", lambda: NOW)())
    manifest = frozen_manifest()
    gateway = HostToolGateway(
        "https://trench.example",
        HostWorkloadIdentity("worker", "ns", "trench"),
        shared_secret="fixture-secret",
        transport=host,
    )

    def admitted_effect(call, context, *, idempotency_key, required_resource, manifest):
        assert required_resource.resource_id == "history"
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
        now=lambda: NOW,
    )
    options.update(kwargs)
    return HostCoverageSnapshotSource(**options), host, options


@pytest.mark.parametrize("bodies", [(), (b"hello",), (b"one", b"two", "中文".encode())])
def test_create_get_without_artifact_store_and_legacy_identity(tmp_path, bodies, monkeypatch):
    def no_artifact_io(*args, **kwargs):
        pytest.fail("source preparation must not perform Artifact I/O")

    with monkeypatch.context() as guarded:
        guarded.setattr(SQLiteArtifactPayloadStore, "__init__", no_artifact_io)
        source, host, options = setup_source(bodies)
        host.short = True
        created = source.create(CONTRACT, authority=AUTHORITY, idempotency_key=" effect-key ")
        fetched = source.get("snapshot", authority=AUTHORITY)
        assert created == fetched
        assert created.records == host.records
        assert created.manifest_bytes == coverage_manifest_bytes(host.records)
        assert not isinstance(created.descriptor, CoverageSnapshot)
        assert not hasattr(created, "manifest_artifact_ref")
        assert not hasattr(source, "artifacts")
        assert host.calls[0]["idempotencyKey"] == " effect-key "
        with pytest.raises(FrozenInstanceError):
            created.manifest_bytes = b"changed"
        with pytest.raises(ValueError):
            created.descriptor.snapshot_id = "changed"
        if created.records:
            with pytest.raises(ValueError):
                created.records[0].record_id = "changed"

    store = SQLiteArtifactPayloadStore(tmp_path / "legacy.sqlite")
    adapter = HostCoverageSnapshotAdapter(**options, artifacts=store, publication_lock=RLock())
    snapshot = adapter.create(CONTRACT, authority=AUTHORITY, idempotency_key=" effect-key ")
    assert snapshot.source_resource_ref == adapter.host.resource.resource_id
    assert snapshot.model_dump(
        exclude={"manifest_artifact_ref", "source_resource_ref"}
    ) == created.descriptor.model_dump()
    assert adapter.manifest_artifact_id(snapshot) == created.manifest_artifact_id
    assert store.read_payload_bytes(created.manifest_artifact_id) == created.manifest_bytes
    before = len(host.calls)
    assert adapter.get("snapshot", authority=AUTHORITY) == snapshot
    assert [c["toolName"].rsplit(".", 1)[1] for c in host.calls[before:]] == ["get"]


@pytest.mark.parametrize(
    "update",
    [
        {"namespace_id": "other"},
        {"host_app_id": "other"},
        {"workspace_ref": "other"},
        {"origin": "https://other.example"},
        {"scopes": ("history.snapshot.write",)},
        {"expires_at": NOW},
        {"expires_at": None},
        {"resource_refs": (HostResourceRef(type="trench.history", id="other"),)},
    ],
)
@pytest.mark.parametrize("operation", ["get", "create"])
def test_invalid_authority_before_host(update, operation):
    source, host, _ = setup_source()
    authority = AUTHORITY.model_copy(update=update)
    with pytest.raises(CoverageRefusedError, match="authority_invalid"):
        if operation == "create":
            source.create(CONTRACT, authority=authority, idempotency_key="key")
        else:
            source.get("snapshot", authority=authority)
    assert not host.calls


@pytest.mark.parametrize(
    "options,reason",
    [
        ({"admitted_effect_invoke": None}, "coverage_unsupported"),
        ({"manifest": None}, "coverage_unsupported"),
        (
            {"authority": AUTHORITY.model_copy(update={"scopes": ("history.read",)})},
            "authority_invalid",
        ),
    ],
)
def test_create_requires_admitted_effect_and_write_scope(options, reason):
    source, host, _ = setup_source(**options)
    with pytest.raises(CoverageRefusedError, match=reason):
        source.create(
            CONTRACT, authority=options.get("authority", AUTHORITY), idempotency_key="key"
        )
    assert not host.calls


@pytest.mark.parametrize("key", ["", " ", "x" * 513, None])
def test_create_key_validation(key):
    source, host, _ = setup_source()
    with pytest.raises(CoverageRefusedError, match="coverage_unsupported"):
        source.create(CONTRACT, authority=AUTHORITY, idempotency_key=key)
    assert not host.calls


@pytest.mark.parametrize(
    "change",
    [
        lambda v: v["scope"].pop("time_field"),
        lambda v: v["snapshot"].update(snapshot_id="other"),
        lambda v: v["snapshot"].update(namespace="other"),
        lambda v: v["snapshot"].update(host_id="other"),
        lambda v: v["snapshot"].update(scope_digest="c" * 64),
        lambda v: v["snapshot"].update(manifest_digest="c" * 64),
        lambda v: v["snapshot"].update(record_count=100001),
        lambda v: v["snapshot"].update(record_count=True),
        lambda v: v["snapshot"].update(expires_at=NOW.isoformat()),
        lambda v: v["provenance"].update(history_ref="other"),
        lambda v: v["provenance"].update(workspace_ref="other"),
        lambda v: v["provenance"].update(periods_digest="c" * 64),
        lambda v: v.update(content_capabilities=[]),
        lambda v: v.update(sealed_at=(NOW + timedelta(hours=1)).isoformat()),
    ],
)
def test_tampered_descriptor(change):
    source, host, _ = setup_source()
    host.mutate = lambda name, v: (change(v) or v) if name == "get" else v
    with pytest.raises(CoverageRefusedError):
        source.get("snapshot", authority=AUTHORITY)


@pytest.mark.parametrize(
    "change",
    [
        lambda v: v["records"].pop(),
        lambda v: v["records"][0].update(ordinal=1),
        lambda v: v["records"][1].update(record_id="r0"),
        lambda v: v["records"].append(v["records"][0]),
        lambda v: v.update(records=[], provenance={}, next_cursor="loop"),
        lambda v: v.update(scope_digest="c" * 64),
        lambda v: v["records"][0]["parts"][0].update(id="other"),
        lambda v: v.update(provenance={}),
        lambda v: v.pop("next_cursor"),
    ],
)
def test_manifest_page_refusals(change):
    source, host, _ = setup_source((b"one", b"two"))
    host.mutate = lambda name, v: rewrite_page(v, change) if name == "page" else v
    with pytest.raises(CoverageRefusedError):
        source.get("snapshot", authority=AUTHORITY)


def test_cursor_loop_and_page_digest():
    source, host, _ = setup_source((b"one", b"two", b"three"))
    host.short = True
    host.mutate = lambda name, v: (
        rewrite_page(v, lambda p: p.update(next_cursor="1")) if name == "page" else v
    )
    with pytest.raises(CoverageRefusedError, match="scope_mismatch"):
        source.get("snapshot", authority=AUTHORITY)
    assert len(host.calls) == 3
    host.mutate = lambda name, v: (v.update(page_digest="c" * 64) or v if name == "page" else v)
    with pytest.raises(CoverageRefusedError, match="manifest_mismatch"):
        source.get("snapshot", authority=AUTHORITY)


@pytest.mark.parametrize("budget", ["calls", "time", "bytes", "empty_bytes"])
def test_bounded_collection(budget):
    ticks = iter([0, 0, 0, 1])
    options = {
        "calls": {"max_calls": 1},
        "time": {"max_seconds": 0.001, "monotonic": lambda: next(ticks, 1)},
        "bytes": {
            "authority": AUTHORITY.model_copy(
                update={"limits": AUTHORITY.limits.model_copy(update={"max_artifact_bytes": 2048})}
            )
        },
        "empty_bytes": {
            "authority": AUTHORITY.model_copy(
                update={"limits": AUTHORITY.limits.model_copy(update={"max_artifact_bytes": 1})}
            )
        },
    }[budget]
    source, host, _ = setup_source(() if budget == "empty_bytes" else (b"item",) * 20, **options)
    host.short = True
    with pytest.raises(CoverageRefusedError, match="budget_exceeded"):
        source.get("snapshot", authority=options.get("authority", AUTHORITY))
    if budget in {"calls", "time"}:
        assert len(host.calls) <= 1
    elif budget == "bytes":
        assert 1 < len(host.calls) < 21


@pytest.mark.parametrize("expiry", ["authority", "snapshot", "time"])
def test_fresh_checks_after_canonical_manifest_before_return(monkeypatch, expiry):
    from agent_integrations import coverage_snapshot_source as module

    tick = [NOW]
    clock = [0.0]
    source, host, _ = setup_source(now=lambda: tick[0], monotonic=lambda: clock[0])
    canonical = module.coverage_manifest_bytes

    def expire(rows):
        body = canonical(rows)
        if rows:
            if expiry == "authority":
                tick[0] = AUTHORITY.expires_at
            elif expiry == "snapshot":
                tick[0] = NOW + timedelta(minutes=30)
            else:
                clock[0] = 60.0
        return body

    monkeypatch.setattr(module, "coverage_manifest_bytes", expire)
    with pytest.raises(
        CoverageRefusedError,
        match={
            "authority": "authority_invalid",
            "snapshot": "snapshot_expired",
            "time": "budget_exceeded",
        }[expiry],
    ):
        source.get("snapshot", authority=AUTHORITY)
    assert len(host.calls) == 2


def test_copied_typed_intent_does_not_confer_authority(tmp_path, monkeypatch):
    source, host, options = setup_source()
    prepared = source.get("snapshot", authority=AUTHORITY)
    forged = replace(
        prepared,
        descriptor=prepared.descriptor.model_copy(update={"host_id": "other"}),
        manifest_bytes=b"tampered",
    )
    # Manifest verification alone cannot validate authority, canonical bytes or full binding.
    verify_manifest(forged.descriptor, forged.records)
    assert forged.manifest_bytes != coverage_manifest_bytes(forged.records)
    assert forged.manifest_artifact_id != source.manifest_artifact_id(forged.descriptor)
    store = SQLiteArtifactPayloadStore(tmp_path / "legacy.sqlite")
    adapter = HostCoverageSnapshotAdapter(**options, artifacts=store, publication_lock=RLock())

    def no_publication(*args, **kwargs):
        pytest.fail("typed intent must not bypass fresh Host authority before publication")

    monkeypatch.setattr(store, "store_payload_immutable", no_publication)
    host.revoked = True
    with pytest.raises(CoverageRefusedError, match="upstream_not_ready"):
        source.get(forged.descriptor.snapshot_id, authority=AUTHORITY)
    with pytest.raises(CoverageRefusedError, match="upstream_not_ready"):
        adapter.get(forged.descriptor.snapshot_id, authority=AUTHORITY)
