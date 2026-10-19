"""API plugin wiring is automatic, default off, and Skill-only needs no MCP secrets."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from zebra_agent_api.plugin_composition import compose_plugins


def test_off_composition_has_no_plugin_io() -> None:
    settings = SimpleNamespace(plugins=SimpleNamespace(enabled=False))
    assert compose_plugins(settings, None, None) == (None, None)


def test_skill_only_composition_reuses_cloud_objects_without_mcp_secrets(tmp_path) -> None:
    settings = SimpleNamespace(
        plugins=SimpleNamespace(
            enabled=True, bundle_root=str(tmp_path), allowed_digests=("sha256:" + "a" * 64,)
        ),
        deployment="cloud",
        storage_authority="postgresql",
        cloud_extensions_manage_enabled=True,
        cloud_extension_turn_admission_enabled=True,
        cloud_skills_publish_enabled=True,
        mcp_credentials=SimpleNamespace(worker_enabled=False),
    )
    cloud = SimpleNamespace(
        dsn="postgresql://unused", deployment_namespace="plugins", artifact_objects=Mock()
    )
    extensions = AsyncMock()
    service, resolver = compose_plugins(settings, cloud, extensions)
    assert service.extensions is extensions and resolver.extensions is extensions
    assert resolver.packages.objects is cloud.artifact_objects
    assert not resolver.allow_mcp
    assert not cloud.artifact_objects.mock_calls
