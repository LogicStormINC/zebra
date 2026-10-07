"""Fail-closed malformed Host wire, authority, durable storage and budgets."""

import base64
import json
import sqlite3
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import pytest
from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.coverage_contracts import (
    CoverageRefusalReason,
    CoverageRefusedError,
    coverage_digest,
)
from agent_core.domain.coverage_persistence import coverage_manifest_bytes
from agent_core.domain.coverage_snapshot import CoveragePageRequest
from agent_core.domain.host_authority import HostResourceRef
from agent_core.domain.identifiers import SessionId
from agent_integrations.coverage_snapshot import HostCoverageSnapshotAdapter

from tests.agent_integrations.test_coverage_snapshot import AUTHORITY, CONTRACT, NOW, setup_adapter


def rewrite_page(value, change):
    change(value)
    value["page_digest"] = coverage_digest({k: v for k, v in value.items() if k != "page_digest"})
    return value


@pytest.mark.parametrize(
    "change",
    [
        lambda v: v["scope"].pop("time_field"),
        lambda v: v["snapshot"].update(namespace="other"),
        lambda v: v["snapshot"].update(host_id="other"),
        lambda v: v["snapshot"].update(scope_digest="c" * 64),
        lambda v: v["snapshot"].update(manifest_digest="c" * 64),
        lambda v: v["snapshot"].update(record_count=True),
        lambda v: v["snapshot"].update(record_count=100001),
        lambda v: v["snapshot"].update(state="revoked"),
        lambda v: v["snapshot"].update(expires_at=(NOW - timedelta(seconds=1)).isoformat()),
        lambda v: v["snapshot"].update(schema_version=True),
        lambda v: v["provenance"].update(history_ref="other"),
        lambda v: v["provenance"].update(workspace_ref="other"),
        lambda v: v["provenance"].update(periods_digest="c" * 64),
        lambda v: v.update(content_capabilities=[]),
        lambda v: v.update(status="pending"),
        lambda v: v["scope"].update(timezone="UTC"),
    ],
)
def test_descriptor_refusals(tmp_path, change):
    adapter, host, _, _ = setup_adapter(tmp_path)

    def mutate(name, value):
        if name == "get":
            change(value)
        return value

    host.mutate = mutate
    with pytest.raises(CoverageRefusedError):
        adapter.get("snapshot", authority=AUTHORITY)


@pytest.mark.parametrize(
    "change",
    [
        lambda v: v["records"].pop(),
        lambda v: v["records"][0].update(ordinal=1),
        lambda v: v["records"][1].update(record_id="r0"),
        lambda v: v["records"].append(v["records"][0]),
        lambda v: v.update(records=[], provenance={}, next_cursor="loop"),
        lambda v: v.update(next_cursor="loop"),
        lambda v: v.update(scope_digest="c" * 64),
        lambda v: v["records"][0]["parts"][0].update(id="unrecognized"),
        lambda v: v["records"][0]["parts"][0].pop("kind"),
        lambda v: v.pop("next_cursor"),
        lambda v: v.update(provenance={}),
    ],
)
def test_manifest_refusals(tmp_path, change):
    adapter, host, _, _ = setup_adapter(tmp_path, (b"first", b"second"))
    host.mutate = lambda name, v: rewrite_page(v, change) if name == "page" else v
    with pytest.raises(CoverageRefusedError):
        adapter.get("snapshot", authority=AUTHORITY)


def test_provenance_is_hashed_before_stripping(tmp_path):
    adapter, host, _, _ = setup_adapter(tmp_path)

    def mutate(name, value):
        if name == "page":
            value["provenance"]["r0"]["title"] = "changed"
        return value

    host.mutate = mutate
    with pytest.raises(CoverageRefusedError, match="manifest_mismatch"):
        adapter.get("snapshot", authority=AUTHORITY)


@pytest.mark.parametrize(
    "change",
    [
        lambda v: v.update(offset=True),
        lambda v: v.update(offset=1),
        lambda v: v.update(next_offset=2),
        lambda v: v.update(next_offset=None),
        lambda v: v.update(byte_length=1),
        lambda v: v.update(digest="c" * 64),
        lambda v: v.update(record_id="other"),
        lambda v: v.update(content_digest="c" * 64),
        lambda v: v.update(namespace="other"),
        lambda v: v.update(data_base64="A==="),
        lambda v: v.update(data_base64=""),
        lambda v: v.update(data_base64=base64.b64encode(b"x" * 32769).decode()),
        lambda v: v.update(data_base64=base64.b64encode(b"x" * 32768).decode()),
    ],
)
def test_body_refusals(tmp_path, change):
    adapter, host, _, _ = setup_adapter(tmp_path, (b"a" * 40000,))
    snapshot = adapter.get("snapshot", authority=AUTHORITY)

    def mutate(name, value):
        if name == "read":
            change(value)
        return value

    host.mutate = mutate
    with pytest.raises(CoverageRefusedError):
        adapter.read(snapshot, host.records[0], host.records[0].parts[0], authority=AUTHORITY)


@pytest.mark.parametrize(
    "update",
    [
        {"namespace_id": "other"},
        {"host_app_id": "other"},
        {"workspace_ref": "other"},
        {"scopes": ("history.snapshot.write",)},
        {"expires_at": NOW - timedelta(seconds=1)},
        {"expires_at": None},
        {"resource_refs": (HostResourceRef(type="trench.history", id="other"),)},
        {
            "resource_refs": (
                *AUTHORITY.resource_refs,
                HostResourceRef(type="trench.history", id="other"),
            )
        },
    ],
)
def test_authority_refusals_before_calls(tmp_path, update):
    adapter, host, _, _ = setup_adapter(tmp_path)
    with pytest.raises(CoverageRefusedError, match="authority_invalid"):
        adapter.get("snapshot", authority=AUTHORITY.model_copy(update=update))
    assert not host.calls


def test_real_storage_corruption_never_overwritten(tmp_path):
    adapter, host, store, options = setup_adapter(tmp_path)
    snapshot = adapter.get("snapshot", authority=AUTHORITY)
    identifier = adapter.manifest_artifact_id(snapshot)
    stored = store.get_payload(identifier)
    path = Path(unquote(urlsplit(stored.access_uri).path))
    path.write_bytes(b"corrupt")
    with pytest.raises(CoverageRefusedError, match="artifact_unavailable"):
        HostCoverageSnapshotAdapter(**options).get("snapshot", authority=AUTHORITY)
    assert path.read_bytes() == b"corrupt"
    assert sum(call["toolName"].endswith("page") for call in host.calls) == 1


def test_cross_session_artifact_refused(tmp_path):
    adapter, host, store, _ = setup_adapter(tmp_path)
    descriptor = adapter._descriptor(
        adapter.host.call(
            "get", {"snapshot_id": "snapshot"}, AUTHORITY, adapter.host.budget(AUTHORITY)
        ),
        AUTHORITY,
    )
    identifier = adapter.manifest_artifact_id(descriptor)
    store.store_payload(
        ArtifactPayloadWrite(
            session_id=SessionId(uuid4()),
            kind="coverage_manifest",
            mime_type="application/octet-stream",
            payload=coverage_manifest_bytes(host.records),
            created_at=NOW,
        ),
        artifact_id=identifier,
    )
    with pytest.raises(CoverageRefusedError, match="artifact_unavailable"):
        adapter.get("snapshot", authority=AUTHORITY)


@pytest.mark.parametrize("options", [{"max_calls": 1}, {"max_seconds": 0.001, "monotonic": None}])
def test_operation_budget(tmp_path, options):
    ticks = iter([0, 0, 0, 1])
    if options.get("monotonic", False) is None:
        options = {**options, "monotonic": lambda: next(ticks, 1)}
    adapter, host, _, _ = setup_adapter(tmp_path, **options)
    with pytest.raises(CoverageRefusedError, match="budget_exceeded"):
        adapter.get("snapshot", authority=AUTHORITY)
    assert len(host.calls) <= 1


def test_request_page_limit_and_exact_membership(tmp_path):
    adapter, host, _, _ = setup_adapter(tmp_path)
    with pytest.raises(CoverageRefusedError):
        adapter.page(
            CoveragePageRequest(
                namespace="ns",
                snapshot_id="snapshot",
                scope_digest=CONTRACT.scope.digest,
                page_size=101,
            ),
            authority=AUTHORITY,
        )
    assert not host.calls
    snapshot = adapter.get("snapshot", authority=AUTHORITY)
    record = host.records[0].model_copy(update={"content_digest": "c" * 64})
    with pytest.raises(CoverageRefusedError, match="part_mismatch"):
        adapter.read(snapshot, record, record.parts[0], authority=AUTHORITY)


@pytest.mark.parametrize(
    "field, value",
    [
        ("lifecycle_status", "pruned"),
        ("sha256", "c" * 64),
        ("size_bytes", 33554433),
        ("session_id", str(uuid4())),
        ("kind", "unrelated"),
        ("mime_type", "text/plain"),
        ("retained_until", (NOW - timedelta(seconds=1)).isoformat()),
    ],
)
def test_durable_metadata_refusals(tmp_path, field, value):
    adapter, _, store, options = setup_adapter(tmp_path)
    snapshot = adapter.get("snapshot", authority=AUTHORITY)
    identifier = adapter.manifest_artifact_id(snapshot)
    with sqlite3.connect(tmp_path / "artifacts.sqlite") as connection:
        connection.execute(
            f"UPDATE artifact_payloads SET {field} = ? WHERE artifact_id = ?",
            (value, str(identifier)),
        )
    with pytest.raises(CoverageRefusedError, match="artifact_unavailable"):
        HostCoverageSnapshotAdapter(**options).get("snapshot", authority=AUTHORITY)
    assert store.get_payload(identifier) is not None


@pytest.mark.parametrize("field", ["created_at", "retained_until"])
def test_naive_sqlite_metadata_timestamps_refused(tmp_path, field):
    adapter, _, _, _ = setup_adapter(tmp_path)
    snapshot = adapter.get("snapshot", authority=AUTHORITY)
    identifier = adapter.manifest_artifact_id(snapshot)
    with sqlite3.connect(tmp_path / "artifacts.sqlite") as connection:
        connection.execute(
            f"UPDATE artifact_payloads SET {field} = ? WHERE artifact_id = ?",
            (NOW.replace(tzinfo=None).isoformat(), str(identifier)),
        )
    with pytest.raises(CoverageRefusedError, match="artifact_unavailable") as refused:
        adapter.get("snapshot", authority=AUTHORITY)
    assert refused.value.reason == CoverageRefusalReason.ARTIFACT_UNAVAILABLE


def test_deleted_and_noncanonical_manifest(tmp_path):
    adapter, host, store, options = setup_adapter(tmp_path)
    snapshot = adapter.get("snapshot", authority=AUTHORITY)
    identifier = adapter.manifest_artifact_id(snapshot)
    path = Path(unquote(urlsplit(store.get_payload(identifier).access_uri).path))
    data = json.dumps(json.loads(coverage_manifest_bytes(host.records))).encode()
    path.write_bytes(data)
    with sqlite3.connect(tmp_path / "artifacts.sqlite") as connection:
        connection.execute(
            "UPDATE artifact_payloads SET sha256 = ?, size_bytes = ? WHERE artifact_id = ?",
            (sha256(data).hexdigest(), len(data), str(identifier)),
        )
    with pytest.raises(CoverageRefusedError, match="artifact_unavailable"):
        HostCoverageSnapshotAdapter(**options).get("snapshot", authority=AUTHORITY)
    path.unlink()
    with pytest.raises(CoverageRefusedError, match="artifact_unavailable"):
        adapter.get("snapshot", authority=AUTHORITY)


def test_corrupt_cached_body_and_expired_snapshot(tmp_path):
    adapter, host, store, options = setup_adapter(tmp_path)
    snapshot = adapter.get("snapshot", authority=AUTHORITY)
    record = host.records[0]
    adapter.read(snapshot, record, record.parts[0], authority=AUTHORITY)
    identifier = adapter.body_artifact_id(snapshot, record, record.parts[0])
    path = Path(unquote(urlsplit(store.get_payload(identifier).access_uri).path))
    path.write_bytes(b"bad")
    fresh = HostCoverageSnapshotAdapter(**options)
    with pytest.raises(CoverageRefusedError, match="artifact_unavailable"):
        fresh.read(snapshot, record, record.parts[0], authority=AUTHORITY)
    assert path.read_bytes() == b"bad"
    expired = HostCoverageSnapshotAdapter(**{**options, "now": lambda: snapshot.expires_at})
    with pytest.raises(CoverageRefusedError, match="snapshot_expired"):
        expired.read(snapshot, record, record.parts[0], authority=AUTHORITY)


def test_declared_body_budget_before_host_read(tmp_path):
    adapter, host, _, _ = setup_adapter(tmp_path)
    record = host.records[0]
    host.records = (
        record.model_copy(
            update={"parts": (record.parts[0].model_copy(update={"byte_length": 33554433}),)}
        ),
    )
    snapshot = adapter.get("snapshot", authority=AUTHORITY)
    record = host.records[0]
    with pytest.raises(CoverageRefusedError, match="budget_exceeded"):
        adapter.read(snapshot, record, record.parts[0], authority=AUTHORITY)
    assert not any(call["toolName"].endswith("read") for call in host.calls)


def test_lost_create_response_same_effect_key_fresh_retry(tmp_path):
    adapter, host, _, options = setup_adapter(tmp_path)
    invoke = options["admitted_effect_invoke"]

    def lose_response(*args, **kwargs):
        invoke(*args, **kwargs)
        raise TimeoutError("response lost after seal")

    first = HostCoverageSnapshotAdapter(**{**options, "admitted_effect_invoke": lose_response})
    with pytest.raises(TimeoutError):
        first.create(CONTRACT, authority=AUTHORITY, idempotency_key=" same-key ")
    retry = HostCoverageSnapshotAdapter(**options)
    snapshot = retry.create(CONTRACT, authority=AUTHORITY, idempotency_key=" same-key ")
    assert snapshot == adapter.get("snapshot", authority=AUTHORITY)
    assert [
        call["idempotencyKey"] for call in host.calls if call["toolName"].endswith("create")
    ] == [" same-key ", " same-key "]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"manifest": None},
        {"invoke": None},
    ],
)
def test_uncomposed_reads_refused(tmp_path, kwargs):
    adapter, host, _, _ = setup_adapter(tmp_path, **kwargs)
    with pytest.raises(CoverageRefusedError, match="coverage_unsupported"):
        adapter.get("snapshot", authority=AUTHORITY)
    assert not host.calls


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_calls": 0},
        {"max_calls": True},
        {"max_calls": 2049},
        {"max_seconds": 0},
        {"max_seconds": float("inf")},
        {"max_seconds": True},
        {"max_seconds": 61},
    ],
)
def test_configured_budget_bounds(tmp_path, kwargs):
    with pytest.raises(ValueError):
        setup_adapter(tmp_path, **kwargs)


def test_cursor_loop_with_positive_short_pages(tmp_path):
    adapter, host, _, _ = setup_adapter(tmp_path, (b"one", b"two", b"three"))
    host.short = True
    host.mutate = (
        lambda name, v: rewrite_page(v, lambda p: p.update(next_cursor="1"))
        if name == "page"
        else v
    )
    with pytest.raises(CoverageRefusedError):
        adapter.get("snapshot", authority=AUTHORITY)
    assert len(host.calls) == 3


def test_noncanonical_base64_padding_bits(tmp_path):
    adapter, host, _, _ = setup_adapter(tmp_path, (b"\x00",))
    snapshot = adapter.get("snapshot", authority=AUTHORITY)

    def mutate(name, value):
        if name == "read":
            value["data_base64"] = "AB=="
        return value

    host.mutate = mutate
    with pytest.raises(CoverageRefusedError, match="part_mismatch"):
        adapter.read(snapshot, host.records[0], host.records[0].parts[0], authority=AUTHORITY)


def test_manifest_byte_budget_with_positive_short_pages(tmp_path):
    limits = AUTHORITY.limits.model_copy(update={"max_artifact_bytes": 2048})
    authority = AUTHORITY.model_copy(update={"limits": limits})
    adapter, host, store, _ = setup_adapter(
        tmp_path, tuple(b"item" for _ in range(20)), authority=authority
    )
    host.short = True
    with pytest.raises(CoverageRefusedError, match="budget_exceeded"):
        adapter.get("snapshot", authority=authority)
    with sqlite3.connect(tmp_path / "artifacts.sqlite") as connection:
        assert connection.execute("SELECT COUNT(*) FROM artifact_payloads").fetchone()[0] == 0
    assert 1 < len(host.calls) < 21
    assert store is not None


def test_authority_expires_during_host_call(tmp_path):
    tick = [NOW]
    adapter, host, _, _ = setup_adapter(tmp_path, now=lambda: tick[0])

    def mutate(name, value):
        tick[0] = AUTHORITY.expires_at
        return value

    host.mutate = mutate
    with pytest.raises(CoverageRefusedError, match="authority_invalid"):
        adapter.get("snapshot", authority=AUTHORITY)
    assert len(host.calls) == 1


def test_existing_oversized_metadata_refused_before_payload_read(tmp_path, monkeypatch):
    adapter, _, store, _ = setup_adapter(tmp_path)
    snapshot = adapter.get("snapshot", authority=AUTHORITY)
    identifier = adapter.manifest_artifact_id(snapshot)
    with sqlite3.connect(tmp_path / "artifacts.sqlite") as connection:
        connection.execute(
            "UPDATE artifact_payloads SET size_bytes = 33554433 WHERE artifact_id = ?",
            (str(identifier),),
        )

    def no_read(identifier):
        pytest.fail("oversized declared payload must be refused before allocation")

    monkeypatch.setattr(store, "read_payload_bytes", no_read)
    with pytest.raises(CoverageRefusedError, match="artifact_unavailable"):
        adapter.get("snapshot", authority=AUTHORITY)


def test_create_write_scope_and_manifest_required(tmp_path):
    adapter, host, _, _ = setup_adapter(tmp_path)
    authority = AUTHORITY.model_copy(update={"scopes": ("history.read",)})
    with pytest.raises(CoverageRefusedError, match="authority_invalid"):
        adapter.create(CONTRACT, authority=authority, idempotency_key="key")
    assert not host.calls


def test_cross_session_snapshot_ref_refused(tmp_path):
    adapter, host, _, options = setup_adapter(tmp_path)
    snapshot = adapter.get("snapshot", authority=AUTHORITY)
    other = HostCoverageSnapshotAdapter(**{**options, "session_id": SessionId(uuid4())})
    with pytest.raises(CoverageRefusedError, match="scope_mismatch"):
        other.read(snapshot, host.records[0], host.records[0].parts[0], authority=AUTHORITY)


def test_empty_terminal_page_for_nonempty_seal_refused(tmp_path):
    adapter, host, _, _ = setup_adapter(tmp_path)
    host.mutate = (
        lambda name, v: rewrite_page(
            v, lambda p: p.update(records=[], provenance={}, next_cursor=None)
        )
        if name == "page"
        else v
    )
    with pytest.raises(CoverageRefusedError, match="manifest_mismatch"):
        adapter.get("snapshot", authority=AUTHORITY)
