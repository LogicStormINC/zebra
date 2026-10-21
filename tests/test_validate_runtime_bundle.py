"""Offline producer contract: real subprocess CLI, redaction and bounded local input."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/contracts/runtime-bundle-v1"
COMMAND = [sys.executable, str(ROOT / "scripts/validate_runtime_bundle.py")]


def invoke(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(COMMAND + list(arguments), capture_output=True, text=True, timeout=10)


def test_generated_public_schema_and_catalog() -> None:
    for flag, name in (
        ("--schema", "envelope.schema.json"),
        ("--catalog", "component-catalog.json"),
    ):
        result = invoke(flag)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == json.loads((CONTRACT / name).read_text())
        assert not result.stderr


def test_real_validator_declares_no_execution_and_does_not_rewrite_input(tmp_path: Path) -> None:
    candidate = tmp_path / "bundle.json"
    original = (CONTRACT / "example-envelope.json").read_bytes()
    candidate.write_bytes(original)
    result = invoke("--input", str(candidate))
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["validation_only"] is True and report["execution_supported"] is False
    assert report["bundle_digest"] == json.loads(original)["bundle_digest"]
    assert report["contract_version"] == "cloud-agent.bundle-validation/1"
    assert candidate.read_bytes() == original
    assert list(tmp_path.iterdir()) == [candidate]


@pytest.mark.parametrize(
    "content",
    [
        b'{"private":"bearer_DO_NOT_ECHO_123",',
        b" " * (262144 + 1),
        b'"secret_DO_NOT_ECHO"',
        b"\xff",
        b'{"x":1,"x":2}',
        b'{"x":Infinity}',
        b'{"x":1.0}',
    ],
)
def test_bad_input_never_echoes_private_data(content: bytes, tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.json"
    candidate.write_bytes(content)
    result = invoke("--input", str(candidate))
    assert result.returncode == 2 and not result.stderr
    assert json.loads(result.stdout) == {"error": {"code": "INVALID_BUNDLE"}}
    assert "DO_NOT_ECHO" not in result.stdout


def test_missing_directory_and_fifo_fail_without_blocking(tmp_path: Path) -> None:
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    for candidate in (tmp_path / "missing", tmp_path, fifo):
        result = invoke("--input", str(candidate))
        assert result.returncode == 2 and not result.stderr
        assert json.loads(result.stdout) == {"error": {"code": "INVALID_BUNDLE"}}
