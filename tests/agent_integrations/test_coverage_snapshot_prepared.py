from datetime import timedelta
from unittest.mock import patch

import pytest
from agent_core.domain.coverage_contracts import CoverageRefusedError

from tests.agent_integrations.test_coverage_snapshot import AUTHORITY, NOW, setup_adapter


def test_prepared_reads_verify_manifest_once_and_still_check_revocation(tmp_path):
    adapter, host, store, _ = setup_adapter(tmp_path, (b"one", b"two", b"three"))
    with patch.object(
        store, "read_payload_bytes_bounded", wraps=store.read_payload_bytes_bounded
    ) as read:
        prepared = adapter.prepare("snapshot", authority=AUTHORITY)
        manifest_id = adapter.manifest_artifact_id(prepared.snapshot)
        for row in prepared.records:
            prepared.read(row, row.parts[0])
        assert sum(call.args[0] == manifest_id for call in read.call_args_list) == 1
        assert len([c for c in host.calls if c["toolName"].endswith("get")]) == 4
        host.revoked = True
        with pytest.raises(CoverageRefusedError):
            prepared.read(prepared.records[0], prepared.records[0].parts[0])


def test_prepared_reader_rejects_pruned_manifest(tmp_path):
    adapter, _, store, _ = setup_adapter(tmp_path, (b"one",))
    prepared = adapter.prepare("snapshot", authority=AUTHORITY)
    store.prune_payload(adapter.manifest_artifact_id(prepared.snapshot))
    with pytest.raises(CoverageRefusedError):
        prepared.read(prepared.records[0], prepared.records[0].parts[0])


@pytest.mark.parametrize("field", ["authority_revision", "manifest_digest", "scope_digest"])
def test_prepared_reader_refuses_descriptor_drift_before_body_access(tmp_path, field):
    adapter, host, _, _ = setup_adapter(tmp_path, (b"one",))
    prepared = adapter.prepare("snapshot", authority=AUTHORITY)

    def change(name, value):
        if name == "get":
            value["snapshot"][field] = "f" * 64
        return value

    host.mutate = change
    before = len([call for call in host.calls if call["toolName"].endswith("read")])
    with pytest.raises(CoverageRefusedError):
        prepared.read(prepared.records[0], prepared.records[0].parts[0])
    assert len([call for call in host.calls if call["toolName"].endswith("read")]) == before


def test_prepared_reader_refuses_expired_grant_before_host_or_body_access(tmp_path):
    clock = [NOW]
    adapter, host, _, _ = setup_adapter(tmp_path, (b"one",), now=lambda: clock[0])
    prepared = adapter.prepare("snapshot", authority=AUTHORITY)
    clock[0] = AUTHORITY.expires_at + timedelta(seconds=1)
    before = len(host.calls)
    with pytest.raises(CoverageRefusedError):
        prepared.read(prepared.records[0], prepared.records[0].parts[0])
    assert len(host.calls) == before
