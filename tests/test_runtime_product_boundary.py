"""Detect new business ownership leaks without removing historical v1 values."""

import pytest

from scripts.check_runtime_product_boundary import DEFAULT_FILES, violations


def test_current_runtime_boundary():
    assert violations() == []


@pytest.mark.parametrize("package", ["trench_core", "trench_api", "trench_models"])
def test_boundary_rejects_new_product_import_literal_and_default_dependency(tmp_path, package):
    for name in DEFAULT_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
    source = tmp_path / "packages/agent-core/src/agent_core/contracts/broker_envelope.py"
    source.parent.mkdir(parents=True)
    source.write_text(f'from {package} import users\nMESSAGE = "trench.ai.turn.ready"\n')
    (tmp_path / DEFAULT_FILES[0]).write_text("depends_on: trench-api")
    errors = violations(tmp_path)
    assert any("product implementation import" in error for error in errors)
    assert any("product broker message" in error for error in errors)
    assert any("default deployment" in error for error in errors)


def test_historical_exception_is_exact_and_not_a_directory_allowlist(tmp_path):
    for name in DEFAULT_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
    source = tmp_path / "packages/agent-core/src/agent_core/domain/coverage_contracts.py"
    source.parent.mkdir(parents=True)
    source.write_text('LEGACY = "trench.subscribed_events"\n')
    assert violations(tmp_path) == []
    source.write_text(source.read_text() + 'NEW = "trench.new_dataset"\n')
    assert len(violations(tmp_path)) == 1
