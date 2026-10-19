"""Small offline checks for acceptance fixture safety and the nonempty v0.2 payload."""

import json

import pytest
from agent_integrations.plugins.package_integrity import load_plugin_package

from tests.cloud_plugins.native_fixture import FILES, bundle, private_config


def test_package_has_real_skill_support_bytes_and_mcp(tmp_path):
    digest = bundle(tmp_path)
    package = load_plugin_package(tmp_path / digest.removeprefix("sha256:"))
    assert package.manifest.manifest_version == "0.2"
    assert {c.kind for c in package.manifest.components} == {"skill-bundle", "mcp-http"}
    assert {f.path.removeprefix("skills/proof/"): f.content for f in package.files} == FILES
    assert all(FILES.values())


def test_private_configuration_rejects_public_permissions(tmp_path):
    path = tmp_path / "private.json"
    path.write_text(json.dumps({}))
    path.chmod(0o644)
    with pytest.raises(AssertionError, match="mode 600"):
        private_config(path)
