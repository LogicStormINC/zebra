from typing import cast

import pytest
from agent_core.domain.extension_snapshots import ExtensionTaskCeiling
from agent_core.ports.artifact_object_store import ArtifactObjectStorePort
from agent_core.ports.extensions import ExtensionStore
from zebra_agent_worker.extension_recovery import RecoveredTurnExtension
from zebra_agent_worker.worker_skill_catalog import (
    WorkerSkillCatalogSource,
    prepare_worker_skill_catalog,
)

from tests.agent_tools.test_cloud_skills import SCOPE, Backend


def _extension(backend: Backend) -> RecoveredTurnExtension:
    return RecoveredTurnExtension(
        scope=SCOPE,
        snapshot=backend.snapshot,
        task_ceiling=cast(ExtensionTaskCeiling, object()),
    )


def test_disabled_and_unbound_worker_paths_do_no_skill_reads() -> None:
    backend = Backend()
    assert (
        prepare_worker_skill_catalog(
            _extension(backend),
            deployment_namespace="test",
            source=None,
        )
        is None
    )
    assert (
        prepare_worker_skill_catalog(
            None,
            deployment_namespace="test",
            source=WorkerSkillCatalogSource(
                cast(ExtensionStore, backend),
                cast(ArtifactObjectStorePort, backend),
            ),
        )
        is None
    )
    assert backend.calls == []


def test_worker_catalog_uses_only_recovered_extension_and_is_lazy() -> None:
    backend = Backend()
    catalog = prepare_worker_skill_catalog(
        _extension(backend),
        deployment_namespace="test",
        source=WorkerSkillCatalogSource(
            cast(ExtensionStore, backend),
            cast(ArtifactObjectStorePort, backend),
        ),
    )
    assert catalog is not None and backend.calls == []
    assert catalog.list()[0][0].name == "sample"
    assert backend.calls == ["authorization"]
    backend.installation = backend.installation.model_copy(update={"enabled": False})
    with pytest.raises(ValueError, match="installation"):
        catalog.read("sample")
    assert "object" not in backend.calls
