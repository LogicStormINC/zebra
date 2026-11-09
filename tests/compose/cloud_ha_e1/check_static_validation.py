"""Check one persisted snapshot validation and immutable native catalog fingerprints."""

import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from agent_core.domain import bundle_definition
from agent_core.domain import runtime_bundle_catalog as catalog
from agent_core.domain.runtime_bundle_json import json_digest
from agent_storage.postgres import workspaces

root = Path(__file__).resolve().parents[3]
snapshot = json.loads((root / "tests/fixtures/runtime_bundle_v1/legacy-v1.json").read_text())[
    "snapshots"
][0]
row = {
    "session_id": str(uuid4()),
    "workspace_root": "/qa/e1",
    "prepared_at": snapshot["resolved_at"],
    "updated_at": snapshot["resolved_at"],
    "current_sequence": 1,
    "status": "prepared",
    "tool_profile": "coding",
    "network_profile": "none",
    "network_allowlist": [],
    "mcp_allowlist": None,
    "skill_components": None,
    "definition_snapshot": snapshot,
}
with (
    patch.object(
        bundle_definition,
        "parse_definition_snapshot",
        wraps=bundle_definition.parse_definition_snapshot,
    ) as parser,
    patch.object(workspaces, "parse_definition_snapshot", parser, create=True),
):
    projection = workspaces._workspace_from_row(row)
    assert parser.call_count == 1, f"persisted snapshot parsed {parser.call_count} times"
assert projection.definition_snapshot is not None
assert projection.definition_snapshot.snapshot_digest == snapshot["snapshot_digest"]
try:
    workspaces._workspace_from_row(
        {**row, "definition_snapshot": {**snapshot, "snapshot_digest": "0" * 64}}
    )
except ValueError as error:
    assert "snapshot_digest" in str(error)
else:
    raise AssertionError("invalid persisted snapshot was accepted")

expected = json.loads(
    (root / "docs/contracts/runtime-bundle-v1/component-catalog.json").read_text()
)
assert catalog.runtime_bundle_catalog() == expected
assert catalog.runtime_bundle_catalog_digest() == json_digest(expected)
for entry in expected["components"]:
    pin = catalog.builtin_component_pin(entry["domain"])
    assert (pin.id, pin.version, pin.digest) == (entry["id"], entry["version"], entry["digest"])
    object.__setattr__(pin, "digest", "sha256:" + "0" * 64)
catalog.runtime_bundle_catalog()["components"][0]["parameters_schema"].clear()
assert catalog.runtime_bundle_catalog() == expected
with patch.object(catalog, "_descriptor", side_effect=AssertionError("static schema regenerated")):
    assert catalog.runtime_bundle_catalog_digest() == json_digest(expected)
    for entry in expected["components"]:
        assert catalog.builtin_component_pin(entry["domain"]).digest == entry["digest"]
print("One typed row validation, tamper rejection, and exact immutable catalog fingerprints.")
