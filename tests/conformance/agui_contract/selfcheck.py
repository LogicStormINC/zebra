"""Offline stdlib integrity/catalog check, deliberately not a JSON Schema validator."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCHEMA_SHA256 = "4b5c93226838a0e72d88e6c5df20633c686c49fcb75d9be2815c6cbf9e48e71a"


def event_catalog(schema: dict) -> list[dict[str, str]]:
    """Follow normative Event.oneOf refs, not incidental enums or other unions."""
    result = []
    for member in schema["$defs"]["Event"]["oneOf"]:
        reference = member["$ref"]
        assert reference.startswith("#/$defs/"), "unexpected external Event reference"
        definition = schema["$defs"][reference.removeprefix("#/$defs/")]
        result.append(
            {
                "type": definition["properties"]["type"]["const"],
                "schema_ref": reference,
                "anchor": definition["$anchor"],
            }
        )
    assert len({item["type"] for item in result}) == len(result), "duplicate event tags"
    return result


def check(root: Path = ROOT) -> None:
    manifest = json.loads((root / "upstream.json").read_text())
    raw = (root / manifest["schema_file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256, "frozen schema bytes changed"
    assert manifest["sha256"] == SCHEMA_SHA256, "manifest hash changed"
    assert len(raw) == manifest["byte_length"] == 94359, "schema length changed"
    schema = json.loads(raw)
    assert schema["$id"] == manifest["schema_id"]
    assert schema["$schema"] == manifest["schema_dialect"]
    assert schema["$ref"] == "#/$defs/Event"
    catalog = event_catalog(schema)
    assert len(catalog) == 31, "official 1.0 event union changed"
    assert {item["type"] for item in catalog} == set(schema["$defs"]["EventType"]["enum"])
    assert catalog == json.loads((root / "event-catalog.json").read_text()), "catalog drift"
    assert manifest["immutable_source_url"] == (
        "https://raw.githubusercontent.com/ag-ui-protocol/ag-ui/"
        + manifest["repository_revision"]
        + "/spec/1.0/schema.json"
    )


if __name__ == "__main__":
    check()
    print("PASS: frozen bytes and 31 normative event tags; schema behavior not certified")
