"""Stored snapshot recovery with actual private bytes; not Worker admission."""

import asyncio
from typing import cast

import pytest
from agent_core.application.extension_configuration import set_extension_enabled
from agent_core.application.skill_installations import create_skill_installation
from agent_core.domain.extension_snapshots import ExtensionSnapshot, ExtensionTaskCeiling
from agent_core.ports.extension_snapshots import ExtensionSnapshotIntegrityError
from agent_storage.artifact_objects import S3ArtifactObjectStore
from agent_storage.postgres.extension_snapshots import PostgresExtensionSnapshotStore
from agent_storage.postgres.extensions import PostgresExtensionStore
from agent_storage.postgres.skill_publications import PostgresSkillPublicationStore
from agent_tools.skill_publications import publish_skill_package
from agent_tools.skills import SkillsReadTool
from agent_tools.skills_catalog import SkillCatalogError
from zebra_agent_worker.extension_recovery import RecoveredTurnExtension
from zebra_agent_worker.worker_skill_catalog import (
    WorkerSkillCatalogSource,
    prepare_worker_skill_catalog,
)

from tests.agent_storage import test_postgres_extensions as fixtures
from tests.agent_storage import test_skill_publication_minio as publication_fixtures
from tests.agent_tools.test_skills import _call

dsn = fixtures.dsn
postgres_dsn = fixtures.postgres_dsn
objects = publication_fixtures.objects


def test_recovered_snapshots_keep_private_bytes_separate_and_do_not_override_disable(
    dsn: str, objects: S3ArtifactObjectStore,
) -> None:
    namespace = "snapshot-recovery"
    configurations = PostgresExtensionStore(dsn, deployment_namespace=namespace)
    publications = PostgresSkillPublicationStore(dsn, deployment_namespace=namespace)
    snapshots = PostgresExtensionSnapshotStore(dsn, deployment_namespace=namespace)

    async def check() -> None:
        prepared = []
        for user, body in (("user-a", "PRIVATE-SNAPSHOT-A"), ("user-b", "PRIVATE-SNAPSHOT-B")):
            scope = fixtures.SCOPE.model_copy(update={"principal_id": user})
            publication = await publish_skill_package(
                archive=publication_fixtures._archive(body), scope=scope,
                deployment_namespace=namespace, store=publications, objects=objects,
            )
            installed, _ = await create_skill_installation(
                store=configurations, scope=scope, idempotency_key="same-install-key",
                payload={"skill_id": publication.version.skill_id,
                         "version_id": publication.version.version_id},
            )
            enabled = await set_extension_enabled(
                store=configurations, scope=scope, kind="skill",
                object_id=installed.installation_id, expected_revision=1, enabled=True,
            )
            snapshot = ExtensionSnapshot(scope=scope, session_id="same-session",
                                         turn_id="same-turn", skills=(enabled,))
            await snapshots.save(scope=scope, snapshot=snapshot)
            prepared.append((snapshot, body))

        # A fresh adapter loads exactly the digest selected by trusted composition.
        restarted = PostgresExtensionSnapshotStore(dsn, deployment_namespace=namespace)
        for expected, body in prepared:
            recovered = await restarted.get(
                scope=expected.scope, session_id=expected.session_id,
                turn_id=expected.turn_id, expected_digest=expected.digest,
            )
            assert recovered == expected
            catalog = await asyncio.to_thread(
                prepare_worker_skill_catalog,
                RecoveredTurnExtension(
                    scope=expected.scope,
                    snapshot=recovered,
                    task_ceiling=cast(ExtensionTaskCeiling, object()),
                ),
                deployment_namespace=namespace,
                source=WorkerSkillCatalogSource(configurations, objects),
            )
            assert catalog is not None
            result = SkillsReadTool(catalog).handle(_call("skills.read", {"name": "sample"}))
            assert body in result.output
            assert all(other not in result.output for _, other in prepared if other != body)
            retry_catalog = await asyncio.to_thread(
                prepare_worker_skill_catalog,
                RecoveredTurnExtension(
                    scope=expected.scope,
                    snapshot=recovered,
                    task_ceiling=cast(ExtensionTaskCeiling, object()),
                ),
                deployment_namespace=namespace,
                source=WorkerSkillCatalogSource(
                    PostgresExtensionStore(dsn, deployment_namespace=namespace), objects,
                ),
            )
            assert retry_catalog is not None
            retry = SkillsReadTool(retry_catalog).handle(
                _call("skills.read", {"name": "sample"})
            )
            assert retry.output == result.output
            with pytest.raises(ExtensionSnapshotIntegrityError):
                await restarted.get(scope=expected.scope, session_id=expected.session_id,
                                    turn_id=expected.turn_id, expected_digest="0" * 64)

            await set_extension_enabled(
                store=configurations, scope=expected.scope, kind="skill",
                object_id=expected.skills[0].installation_id, expected_revision=2, enabled=False,
            )
            # Historical persistence is not live execution authority.
            with pytest.raises(SkillCatalogError):
                catalog.read("sample")

    asyncio.run(check())
