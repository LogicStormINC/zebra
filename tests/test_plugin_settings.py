"""Cloud plugin routes default off and consume operator-only full digests."""

import pytest
from zebra_agent_config import load_settings


def test_plugin_settings_default_off_and_explicit_operator_values() -> None:
    default = load_settings({}).plugins
    assert not default.enabled and default.bundle_root == "" and default.allowed_digests == ()
    digest = "sha256:" + "a" * 64
    configured = load_settings(
        {
            "ZEBRA_CLOUD_PLUGINS_ENABLED": "true",
            "ZEBRA_CLOUD_PLUGIN_BUNDLE_ROOT": "/mnt/plugins",
            "ZEBRA_CLOUD_PLUGIN_ALLOWED_DIGESTS": digest,
        }
    ).plugins
    assert configured.enabled and configured.bundle_root == "/mnt/plugins"
    assert configured.allowed_digests == (digest,)
    with pytest.raises(ValueError):
        load_settings({"ZEBRA_CLOUD_PLUGIN_ALLOWED_DIGESTS": "sha256:abcd"})
