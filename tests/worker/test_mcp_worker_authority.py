"""MCP consumes real bound Worker evidence without constructing an HTTP Grant."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from agent_security.host_grant import HostGrantBindingError

from tests.agent_runtime import test_mcp_execution_authorization as fixtures
from tests.worker.test_worker_mcp_catalog import worker_authority

protector = fixtures.protector


def test_worker_evidence_releases_bearer(tmp_path, protector):
    callback = fixtures.resolver(tmp_path, protector)
    evidence = worker_authority(callback)
    callback = replace(callback, fresh_authority=lambda: evidence)
    credential = callback(callback.endpoint, {"method": "initialize"})
    assert credential is not None
    callback.release.store.get_for_use.assert_awaited_once()


@pytest.mark.parametrize("change", [
    "session", "issuer", "namespace", "binding", "policy", "definition",
    "expired", "future", "capabilities", "current_task",
])
def test_worker_evidence_drift_blocks_credential_read(tmp_path, protector, change):
    callback = fixtures.resolver(tmp_path, protector)
    evidence = worker_authority(callback)
    updates = {
        "issuer": {"authority_issuer": "https://other.example.com"},
        "namespace": {"namespace_id": "other"},
        "binding": {"source_authority_digest": "f" * 64},
        "policy": {"policy_effective_digest": "f" * 64},
        "definition": {"agent_definition_snapshot_digest": "f" * 64},
        "expired": {"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
        "future": {"validated_at": datetime.now(UTC) + timedelta(minutes=1)},
        "capabilities": {"granted_authorities": ("evidence.read",)},
    }
    if change in updates:
        evidence = replace(evidence, snapshot=evidence.snapshot.model_copy(
            update=updates[change] | {"snapshot_digest": None}
        ))
    elif change == "session":
        evidence = replace(evidence, session_id="another-session")
    else:
        ceiling = callback.release.tasks.resolve_task_ceiling.return_value
        callback.release.tasks.resolve_task_ceiling.return_value = ceiling.model_copy(
            update={"binding": ceiling.binding.model_copy(update={"binding_revision": 2})}
        )
    callback = replace(callback, fresh_authority=lambda: evidence)
    with pytest.raises((HostGrantBindingError, ValueError)):
        callback(callback.endpoint, {"method": "initialize"})
    callback.release.store.get_for_use.assert_not_called()
