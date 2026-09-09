"""Real ZIP publication/recovery with a disposable PG schema and private S3 bucket."""

import asyncio
import io
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4
from zipfile import ZipFile

import pytest
from agent_core.ports.skill_publications import SkillPublicationStorePort
from agent_storage.artifact_objects import S3ArtifactObjectStore
from agent_storage.postgres.skill_publications import PostgresSkillPublicationStore
from agent_tools.skill_publications import publish_skill_package

from tests.agent_storage import test_postgres_extensions as fixtures
from tests.agent_storage.test_s3_artifact_objects_minio import _client

dsn = fixtures.dsn
postgres_dsn = fixtures.postgres_dsn


@pytest.fixture
def objects() -> Generator[S3ArtifactObjectStore, None, None]:
    client: Any = _client()
    bucket = f"zebra-skill-test-{uuid4().hex}"
    client.create_bucket(Bucket=bucket)
    try:
        client.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
        yield S3ArtifactObjectStore(client, bucket=bucket, key_prefix="skills")
    finally:
        # Only this newly created, test-owned bucket is enumerated or removed.
        for page in client.get_paginator("list_object_versions").paginate(Bucket=bucket):
            versions = [
                {"Key": entry["Key"], "VersionId": entry["VersionId"]}
                for field in ("Versions", "DeleteMarkers") for entry in page.get(field, [])
            ]
            if versions:
                response = client.delete_objects(Bucket=bucket, Delete={"Objects": versions})
                assert not response.get("Errors"), "Test object cleanup failed"
        client.delete_bucket(Bucket=bucket)


def _archive(body: str) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as bundle:
        bundle.writestr("SKILL.md", "---\nname: sample\ndescription: Example skill\n"
                        f"version: 1.0\n---\n{body}\n")
    return buffer.getvalue()


def test_real_package_recovers_and_keeps_user_bytes_separate(
    dsn: str, objects: S3ArtifactObjectStore,
) -> None:
    namespace = "skill-publication-live"
    store = PostgresSkillPublicationStore(dsn, deployment_namespace=namespace)
    interrupted = AsyncMock(spec=SkillPublicationStorePort, wraps=store)
    interrupted.mark_ready.side_effect = RuntimeError("simulated failure after upload")
    archive = _archive("User A instructions")

    async def check() -> None:
        with pytest.raises(RuntimeError, match="simulated failure"):
            await publish_skill_package(archive=archive, scope=fixtures.SCOPE,
                                        deployment_namespace=namespace,
                                        store=interrupted, objects=objects)
        candidate = interrupted.reserve.await_args.kwargs["publication"]
        pending = await store.get(scope=fixtures.SCOPE, skill_id=candidate.version.skill_id,
                                  version_id=candidate.version.version_id)
        assert pending.state == "publishing" and pending.receipt is None
        first_object = objects.verify(pending.expectation).receipt
        assert first_object is not None and first_object.object_version != "null"

        fresh = PostgresSkillPublicationStore(dsn, deployment_namespace=namespace)
        ready = await publish_skill_package(archive=archive, scope=fixtures.SCOPE,
                                           deployment_namespace=namespace,
                                           store=fresh, objects=objects)
        assert ready.state == "ready" and ready.receipt == first_object
        assert objects.read_verified(ready.expectation) == archive
        assert await publish_skill_package(archive=archive, scope=fixtures.SCOPE,
                                           deployment_namespace=namespace,
                                           store=fresh, objects=objects) == ready

        other_archive = _archive("User B private instructions")
        other = await publish_skill_package(
            archive=other_archive,
            scope=fixtures.SCOPE.model_copy(update={"principal_id": "user-b"}),
            deployment_namespace=namespace, store=fresh, objects=objects,
        )
        assert other.expectation.artifact_id != ready.expectation.artifact_id
        assert objects.read_verified(other.expectation) == other_archive
        assert objects.read_verified(ready.expectation) == archive
        assert await fresh.get(scope=fixtures.SCOPE, skill_id=ready.version.skill_id,
                               version_id=ready.version.version_id) == ready

    asyncio.run(check())
