"""Accepted legacy snapshots stay immutable; missing Plugin origin suspends before model IO."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agent_core.domain.extension_snapshots import ExtensionSnapshot
from agent_core.domain.plugin_authority import PluginAuthorityUnavailable
from agent_core.domain.plugin_snapshots import PluginSnapshot
from agent_core.ports.plugin_installations import PluginInstallationPage
from zebra_agent_worker.extension_recovery import RecoveredTurnExtension
from zebra_agent_worker.worker_plugins import WorkerPluginSource, prepare_worker_plugins

from tests.agent_core.test_plugin_component_ownership import skill_plugin


@pytest.mark.parametrize("legacy", [False, True])
def test_old_direct_managed_snapshot_suspends_without_mutating_snapshot_or_package_io(legacy):
    backend, record = skill_plugin(legacy=legacy, enabled=False)
    snapshot = ExtensionSnapshot(scope=record.scope, session_id="session", turn_id="turn",
                                 skills=(backend.installation,))
    digest = snapshot.digest
    extension = RecoveredTurnExtension(record.scope, snapshot, SimpleNamespace())
    installations, packages = AsyncMock(), AsyncMock()
    installations.list.return_value = PluginInstallationPage(items=(record,))
    source = WorkerPluginSource(installations, packages)
    with pytest.raises(PluginAuthorityUnavailable, match="origin"):
        prepare_worker_plugins(extension, source=source, skills_available=True, mcp_available=False)
    assert snapshot.digest == digest and not snapshot.plugins
    packages.read.assert_not_awaited()


def test_shared_legacy_origin_survives_disabled_plugin_and_managed_origin_requires_pin():
    backend, record = skill_plugin(managed=False, enabled=False)
    snapshot = ExtensionSnapshot(scope=record.scope, session_id="session", turn_id="turn",
                                 skills=(backend.installation,))
    installations, packages = AsyncMock(), AsyncMock()
    installations.list.return_value = PluginInstallationPage(items=(record,))
    source = WorkerPluginSource(installations, packages)
    extension = RecoveredTurnExtension(record.scope, snapshot, SimpleNamespace())
    assert prepare_worker_plugins(extension, source=source, skills_available=True,
                                  mcp_available=False) is None
    packages.read.assert_not_awaited()
    backend, record = skill_plugin()
    snapshot = ExtensionSnapshot(scope=record.scope, session_id="session", turn_id="turn",
        skills=(backend.installation,), plugins=(PluginSnapshot.from_installation(record),))
    extension = RecoveredTurnExtension(record.scope, snapshot, SimpleNamespace())
    installations.get_current_batch.return_value = (record,)
    installations.get_revision.return_value = record
    guard = prepare_worker_plugins(extension, source=source, skills_available=True,
                                   mcp_available=False)
    guard.validate()
    installations.get_current_batch.return_value = ()
    with pytest.raises(PluginAuthorityUnavailable):
        guard.validate()
    packages.read.assert_awaited_once_with(record.package)


def test_feature_off_ownership_reader_denies_managed_and_preserves_standalone():
    from zebra_agent_worker.plugin_composition import compose_worker_plugins

    settings = SimpleNamespace(
        plugins=SimpleNamespace(enabled=False),
        deployment="cloud",
        storage_authority="postgresql",
        cloud_extension_worker_enabled=True,
    )
    cloud = SimpleNamespace(
        dsn="postgresql://unused",
        deployment_namespace="scope",
        extension_snapshots=object(),
        skill_objects=None,
        stores=SimpleNamespace(task_io_connections=None),
    )
    composed = compose_worker_plugins(settings, cloud)
    assert composed is not None and composed.packages is None
    for managed in (False, True):
        backend, record = skill_plugin(legacy=True, managed=managed, enabled=False)
        snapshots = ExtensionSnapshot(
            scope=record.scope, session_id="session", turn_id="turn", skills=(backend.installation,)
        )
        extension = RecoveredTurnExtension(record.scope, snapshots, SimpleNamespace())
        store = AsyncMock()
        store.list.return_value = PluginInstallationPage(items=(record,))
        guarded = WorkerPluginSource(store, None)
        if managed:
            with pytest.raises(PluginAuthorityUnavailable):
                prepare_worker_plugins(
                    extension, source=guarded, skills_available=True, mcp_available=False
                )
        else:
            assert (
                prepare_worker_plugins(
                    extension, source=guarded, skills_available=True, mcp_available=False
                )
                is None
            )
        with pytest.raises(PluginAuthorityUnavailable, match="ownership reader"):
            prepare_worker_plugins(
                extension, source=None, skills_available=True, mcp_available=False
            )
        selected = snapshots.model_copy(
            update={"plugins": (PluginSnapshot.from_installation(record),)}
        )
        with pytest.raises(PluginAuthorityUnavailable):
            prepare_worker_plugins(
                RecoveredTurnExtension(record.scope, selected, SimpleNamespace()),
                source=guarded,
                skills_available=True,
                mcp_available=False,
            )
    assert (
        prepare_worker_plugins(None, source=None, skills_available=False, mcp_available=False)
        is None
    )
