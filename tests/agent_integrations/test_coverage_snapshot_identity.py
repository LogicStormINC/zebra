"""Verified Host history becomes local snapshot identity, never a new wire field."""

import pytest
from agent_core.domain.coverage_contracts import CoverageRefusedError

from tests.agent_integrations.test_coverage_snapshot import AUTHORITY, CONTRACT, setup_adapter


@pytest.mark.parametrize("operation", ["create", "get"])
def test_adapter_populates_verified_history_and_keeps_wire_descriptor_unchanged(
    tmp_path, operation
):
    adapter, wire, _, _ = setup_adapter(tmp_path, (b"one",))
    value = (
        adapter.create(CONTRACT, authority=AUTHORITY, idempotency_key="identity")
        if operation == "create"
        else adapter.get("snapshot", authority=AUTHORITY)
    )
    assert value.source_resource_ref == adapter.host.resource.resource_id == "history"
    descriptor = adapter.source._get_descriptor(
        "snapshot", AUTHORITY, adapter.host.budget(AUTHORITY)
    )
    assert "source_resource_ref" not in descriptor.model_dump()
    assert (
        value.model_dump(exclude={"manifest_artifact_ref", "source_resource_ref"})
        == descriptor.model_dump()
    )
    assert wire.calls


def test_foreign_wire_history_is_refused_before_local_snapshot_publication(tmp_path):
    adapter, wire, store, _ = setup_adapter(tmp_path, (b"one",))

    def foreign(name, value):
        if name in {"get", "create"}:
            value["provenance"]["history_ref"] = "foreign"
        return value

    wire.mutate = foreign
    with pytest.raises(CoverageRefusedError):
        adapter.get("snapshot", authority=AUTHORITY)
    with store._database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM artifact_payloads").fetchone()[0] == 0


def test_legacy_snapshot_without_local_source_remains_readable(tmp_path):
    adapter, wire, _, _ = setup_adapter(tmp_path, (b"one",))
    current = adapter.get("snapshot", authority=AUTHORITY)
    legacy = current.model_copy(update={"source_resource_ref": None})
    assert (
        adapter.read(
            legacy, wire.records[0], wire.records[0].parts[0], authority=AUTHORITY
        ).snapshot_id
        == "snapshot"
    )


def test_prepared_reader_keeps_local_source_out_of_wire_descriptor_comparison(tmp_path):
    adapter, _, _, _ = setup_adapter(tmp_path, (b"one",))
    prepared = adapter.prepare("snapshot", authority=AUTHORITY)
    assert prepared.snapshot.source_resource_ref == "history"
    record = prepared.records[0]
    assert prepared.read(record, record.parts[0]).snapshot_id == "snapshot"


@pytest.mark.parametrize("reader", ["ordinary", "prepared"])
def test_foreign_local_source_is_refused_before_any_body_access(tmp_path, reader):
    adapter, wire, _, _ = setup_adapter(tmp_path, (b"one",))
    prepared = adapter.prepare("snapshot", authority=AUTHORITY)
    foreign = prepared.snapshot.model_copy(update={"source_resource_ref": "foreign"})
    record = prepared.records[0]
    before = sum(call["toolName"].endswith("read") for call in wire.calls)
    with pytest.raises(CoverageRefusedError):
        if reader == "ordinary":
            adapter.read(foreign, record, record.parts[0], authority=AUTHORITY)
        else:
            prepared.snapshot = foreign
            prepared.read(record, record.parts[0])
    assert sum(call["toolName"].endswith("read") for call in wire.calls) == before


def test_prepared_reader_cannot_erase_verified_source_as_legacy(tmp_path):
    adapter, _, _, _ = setup_adapter(tmp_path, (b"one",))
    prepared = adapter.prepare("snapshot", authority=AUTHORITY)
    prepared.snapshot = prepared.snapshot.model_copy(update={"source_resource_ref": None})
    record = prepared.records[0]
    with pytest.raises(CoverageRefusedError):
        prepared.read(record, record.parts[0])
