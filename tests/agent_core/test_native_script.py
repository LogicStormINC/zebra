import json
from hashlib import sha256
from pathlib import Path

import pytest
from agent_core.domain.native_script import NativeScriptError, parse_native_script
from agent_core.domain.runtime_bundle_json import canonical_json_bytes
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2] / "docs/contracts/native-script-v1"
VECTORS = json.loads((ROOT / "positive-vectors.json").read_text())
NEGATIVES = json.loads((ROOT / "negative-vectors.json").read_text())


@pytest.mark.parametrize("vector", VECTORS, ids=lambda item: item["name"])
def test_fixed_manifest_source_and_output_identity(vector: dict) -> None:
    script = parse_native_script(json.dumps(vector["manifest"]).encode(), vector["source"].encode())
    assert script.manifest.digest == vector["manifest_digest"]
    script.manifest.input.validate_record(vector["invocation"]["arguments"])
    script.manifest.output.validate_record(vector["output"])
    assert (
        "sha256:" + sha256(canonical_json_bytes(vector["output"])).hexdigest()
        == vector["output_digest"]
    )
    with pytest.raises(ValidationError):
        script.manifest.input.fields[0].name = "changed"


@pytest.mark.parametrize("vector", NEGATIVES, ids=lambda item: item["name"])
def test_unsupported_configuration_never_becomes_executable(vector: dict) -> None:
    base = VECTORS[0]
    manifest = base["manifest"] | vector["manifestPatch"]
    with pytest.raises(NativeScriptError, match="invalid_script_package"):
        parse_native_script(json.dumps(manifest).encode(), base["source"].encode())


@pytest.mark.parametrize(
    "value", [{}, {"query": True}, {"query": "x", "extra": 1}, {"query": "x" * 4097}]
)
def test_closed_input_shape(value: dict) -> None:
    base = VECTORS[0]
    shape = parse_native_script(
        json.dumps(base["manifest"]).encode(), base["source"].encode()
    ).manifest.input
    with pytest.raises(NativeScriptError):
        shape.validate_record(value)


@pytest.mark.parametrize(
    "raw", [b'{"abi":"x","abi":"y"}', b"\xef\xbb\xbf{}", b'{"x": NaN}', b'{"x":1.0}', b"{}\x00"]
)
def test_strict_json_has_no_duplicate_float_or_hidden_suffix(raw: bytes) -> None:
    with pytest.raises(NativeScriptError):
        parse_native_script(raw, b"pass")


def test_source_size_bytes_syntax_and_unicode_are_checked() -> None:
    base = VECTORS[0]
    for source in (b"", b"#" * 16385, b"def broken", b"\xff"):
        manifest = base["manifest"] | {"source_digest": "sha256:" + sha256(source).hexdigest()}
        with pytest.raises(NativeScriptError):
            parse_native_script(json.dumps(manifest).encode(), source)


def test_manifest_and_nonbyte_sources_have_bounded_parsing() -> None:
    base = VECTORS[0]
    with pytest.raises(NativeScriptError):
        parse_native_script(b" " * 16385, base["source"].encode())
    with pytest.raises(NativeScriptError):
        parse_native_script(json.dumps(base["manifest"]).encode(), base["source"])
