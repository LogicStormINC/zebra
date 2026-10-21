"""Separate private authority and unchanged historical Worker baseline."""

import os
from dataclasses import replace

import pytest
from zebra_agent_api.script_validation_config import load_script_validation_approval
from zebra_agent_config import load_settings
from zebra_agent_config.bundle_settings import baseline_digest

from tests.api.test_bundle_management import write
from tests.api.test_script_validation import configured_fixture
from tests.test_bundle_assembly import settings


def test_setting_does_not_change_old_baseline(tmp_path):
    expected = "sha256:c7748ed8d32a5c534d4c7c8290fd71f5d5d3c01d46c3d38c53665a5cce900fdc"
    active = settings()
    assert baseline_digest(active, "ab" * 32) == expected
    assert (
        baseline_digest(replace(active, script_validation_config="/private/approval"), "ab" * 32)
        == expected
    )
    loaded = load_settings({"ZEBRA_SCRIPT_VALIDATION_CONFIG": str(tmp_path / "approval")})
    assert loaded.script_validation_config == str(tmp_path / "approval")


def test_private_approval_is_closed_and_namespace_bound(tmp_path):
    _, path, approval, _, _ = configured_fixture(tmp_path)
    assert load_script_validation_approval(str(path), "local").trust_revision == 1
    assert "credential_sha256" not in repr(load_script_validation_approval(str(path), "local"))
    for change in (
        {"schema_version": "cloud-agent.bundle-management-approval/1"},
        {"actions": ["bundle.validate"]},
        {"actions": ["script.validate", "script.validate"]},
        {"actions": []},
        {"trust_revision": True},
        {"trust_revision": 0},
        {"credential_sha256": "not-a-digest"},
        {"expires_at": "2099-01-01"},
        {"expires_at": "2099-01-01T00:00:00+00:00"},
        {"extra": "DO_NOT_ECHO"},
    ):
        write(path, {**approval, **change})
        with pytest.raises(ValueError, match="^INVALID_SCRIPT_VALIDATION_APPROVAL$"):
            load_script_validation_approval(str(path), "local")
    write(path, approval)
    for namespace in (None, "other"):
        with pytest.raises(ValueError, match="^INVALID_SCRIPT_VALIDATION_APPROVAL$"):
            load_script_validation_approval(str(path), namespace)
    for mode in (0o644, 0o200):
        path.chmod(mode)
        with pytest.raises(ValueError, match="^INVALID_SCRIPT_VALIDATION_APPROVAL$"):
            load_script_validation_approval(str(path), "local")
    path.chmod(0o400)
    assert load_script_validation_approval(str(path), "local").actions
    path.unlink()
    os.mkfifo(path, 0o600)
    with pytest.raises(ValueError, match="^INVALID_SCRIPT_VALIDATION_APPROVAL$"):
        load_script_validation_approval(str(path), "local")
    path.unlink()
    path.write_bytes(b" " * 16385)
    path.chmod(0o600)
    with pytest.raises(ValueError, match="^INVALID_SCRIPT_VALIDATION_APPROVAL$"):
        load_script_validation_approval(str(path), "local")
    for missing in (None, "relative", str(tmp_path / "missing")):
        with pytest.raises(ValueError, match="^INVALID_SCRIPT_VALIDATION_APPROVAL$"):
            load_script_validation_approval(missing, "local")
