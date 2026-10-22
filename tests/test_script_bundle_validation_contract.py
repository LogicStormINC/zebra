"""Exported producer schema/digests and parser vectors, not execution evidence."""

import json
from hashlib import sha256
from pathlib import Path

import pytest
from agent_core.domain.script_bundle import ScriptBundle
from zebra_agent_api.script_bundle_contract import native_script_bundle_contract

ROOT = Path("docs/contracts/script-bundle-validation")


def test_exact_producer_exports_and_native_vectors():
    assert json.loads((ROOT / "contract.json").read_bytes()) == native_script_bundle_contract()
    assert (
        json.loads((ROOT / "request.schema.json").read_bytes()) == ScriptBundle.model_json_schema()
    )
    for vector in json.loads((ROOT / "vectors.json").read_bytes()):
        raw = vector["raw"].encode()
        assert vector["inputDigest"] == "sha256:" + sha256(raw).hexdigest()
        if vector["nativeParseValid"]:
            ScriptBundle.model_validate_json(raw)
        else:
            with pytest.raises(ValueError):
                ScriptBundle.model_validate_json(raw)
