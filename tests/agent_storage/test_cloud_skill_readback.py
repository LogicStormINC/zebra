"""Actual private package publication, install and tool readback; not live Worker admission."""

import asyncio

import psycopg
import pytest
from agent_core.application.extension_configuration import set_extension_enabled
from agent_core.application.skill_installations import create_skill_installation
from agent_core.domain.extension_snapshots import ExtensionSnapshot
from agent_core.domain.extensions import ExtensionScope
from agent_core.domain.tools import ToolCallStatus
from agent_storage.artifact_objects import S3ArtifactObjectStore
from agent_storage.postgres.extensions import PostgresExtensionStore
from agent_storage.postgres.skill_publications import PostgresSkillPublicationStore
from agent_tools.cloud_skills import prepare_cloud_skill_catalog
from agent_tools.skill_publications import publish_skill_package
from agent_tools.skills import SkillsListTool, SkillsReadTool
from agent_tools.skills_catalog import SkillCatalogError

from tests.agent_storage import test_postgres_extensions as fixtures
from tests.agent_storage import test_skill_publication_minio as publication_fixtures
from tests.agent_tools.test_skills import _call

dsn = fixtures.dsn
postgres_dsn = fixtures.postgres_dsn
objects = publication_fixtures.objects


def test_private_published_bytes_reach_existing_tools_without_local_files(
    dsn: str,
    objects: S3ArtifactObjectStore,
) -> None:
    namespace = "cloud-skill-readback"
    store = PostgresExtensionStore(dsn, deployment_namespace=namespace)
    publications = PostgresSkillPublicationStore(dsn, deployment_namespace=namespace)

    async def prepare(scope: ExtensionScope, body: str) -> ExtensionSnapshot:
        ready = await publish_skill_package(
            archive=publication_fixtures._archive(body),
            scope=scope,
            deployment_namespace=namespace,
            store=publications,
            objects=objects,
        )
        installed, created = await create_skill_installation(
            store=store,
            scope=scope,
            idempotency_key="same-install-key",
            payload={"skill_id": ready.version.skill_id, "version_id": ready.version.version_id},
        )
        assert created and not installed.enabled
        enabled = await set_extension_enabled(
            store=store,
            scope=scope,
            kind="skill",
            object_id=installed.installation_id,
            expected_revision=1,
            enabled=True,
        )
        return ExtensionSnapshot(
            scope=scope,
            session_id="session",
            turn_id="turn",
            skills=(enabled,),
        )

    async def check() -> None:
        scope_a = fixtures.SCOPE
        scope_b = scope_a.model_copy(update={"principal_id": "user-b"})
        snapshot_a = await prepare(scope_a, "PRIVATE-A: summarize subscriptions")
        snapshot_b = await prepare(scope_b, "PRIVATE-B: compare historical sources")
        for snapshot, own, other in (
            (snapshot_a, "PRIVATE-A", "PRIVATE-B"),
            (snapshot_b, "PRIVATE-B", "PRIVATE-A"),
        ):
            catalog = await prepare_cloud_skill_catalog(
                snapshot=snapshot,
                scope=snapshot.scope,
                deployment_namespace=namespace,
                session_id="session",
                turn_id="turn",
                store=store,
                objects=objects,
            )
            listed = SkillsListTool(catalog).handle(_call("skills.list", {}))
            read = SkillsReadTool(catalog).handle(_call("skills.read", {"name": "sample"}))
            assert listed.status is read.status is ToolCallStatus.EXECUTED
            assert own not in listed.output and other not in listed.output
            assert own in read.output and other not in read.output
            assert "CLOUD" in read.output and "LOCAL" not in read.output
            assert read.metadata["skill_digest"] == snapshot.skills[0].version.content_digest
            assert read.metadata["untrusted_procedural_guidance"] is True

        class RevokingObjects:
            def read_version_verified(self, expectation, object_version):
                payload = objects.read_version_verified(expectation, object_version)
                frozen = snapshot_b.skills[0]
                store._save(
                    scope_b,
                    "skill",
                    frozen.model_copy(update={"revision": 3, "enabled": False}),
                    2,
                )
                return payload

        during_read = await prepare_cloud_skill_catalog(
            snapshot=snapshot_b,
            scope=scope_b,
            deployment_namespace=namespace,
            session_id="session",
            turn_id="turn",
            store=store,
            objects=RevokingObjects(),  # type: ignore[arg-type]
        )
        with pytest.raises(SkillCatalogError, match="unavailable"):
            during_read.read("sample")
        with pytest.raises(SkillCatalogError):
            await prepare_cloud_skill_catalog(
                snapshot=snapshot_a,
                scope=scope_b,
                deployment_namespace=namespace,
                session_id="session",
                turn_id="turn",
                store=store,
                objects=objects,
            )
        await set_extension_enabled(
            store=store,
            scope=scope_a,
            kind="skill",
            object_id=snapshot_a.skills[0].installation_id,
            expected_revision=2,
            enabled=False,
        )
        revoked = await prepare_cloud_skill_catalog(
            snapshot=snapshot_a,
            scope=scope_a,
            deployment_namespace=namespace,
            session_id="session",
            turn_id="turn",
            store=store,
            objects=objects,
        )
        with pytest.raises(SkillCatalogError):
            revoked.list()

    asyncio.run(check())


def test_forged_ready_receipt_version_cannot_read_current_object(
    dsn: str,
    objects: S3ArtifactObjectStore,
) -> None:
    namespace = "cloud-skill-version-pin"
    scope = fixtures.SCOPE
    store = PostgresExtensionStore(dsn, deployment_namespace=namespace)
    publications = PostgresSkillPublicationStore(dsn, deployment_namespace=namespace)

    async def publish_and_install():
        ready = await publish_skill_package(
            archive=publication_fixtures._archive("PINNED-VERSION"),
            scope=scope,
            deployment_namespace=namespace,
            store=publications,
            objects=objects,
        )
        candidate, _ = await create_skill_installation(
            store=store,
            scope=scope,
            idempotency_key="pinned-version",
            payload={"skill_id": ready.version.skill_id, "version_id": ready.version.version_id},
        )
        installed = await set_extension_enabled(
            store=store,
            scope=scope,
            kind="skill",
            object_id=candidate.installation_id,
            expected_revision=1,
            enabled=True,
        )
        return ready, installed

    ready, installed = asyncio.run(publish_and_install())
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE skill_package_versions SET payload=jsonb_set(payload, "
            "'{receipt,object_version}', to_jsonb(%s::text)) "
            "WHERE deployment_namespace=%s AND skill_id=%s AND version_id=%s",
            ("forged-object-version", namespace, ready.version.skill_id, ready.version.version_id),
        )
    snapshot = ExtensionSnapshot(
        scope=scope,
        session_id="session",
        turn_id="turn",
        skills=(installed,),
    )
    catalog = asyncio.run(
        prepare_cloud_skill_catalog(
            snapshot=snapshot,
            scope=scope,
            deployment_namespace=namespace,
            session_id="session",
            turn_id="turn",
            store=store,
            objects=objects,
        )
    )
    with pytest.raises(SkillCatalogError) as caught:
        catalog.read("sample")
    assert caught.value.reason == "package_integrity"
