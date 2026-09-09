"""Normal cloud startup and uploads using disposable real PostgreSQL and MinIO."""

import asyncio
import os
from dataclasses import replace

import pytest
from agent_security.extension_authority import extension_scope_from_grant
from agent_storage import cloud_composition_from_environment
from agent_storage.artifact_objects import S3ArtifactObjectStore
from agent_storage.postgres.skill_publications import PostgresSkillPublicationStore
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app

from tests.agent_security.test_extension_authority import _verified
from tests.agent_storage import test_postgres_extensions as fixtures
from tests.agent_storage import test_skill_publication_minio as publication_fixtures
from tests.api.test_extension_reads import AUTH, Authorizer
from tests.api.test_host_auth_http import _cloud_settings

dsn = fixtures.dsn
postgres_dsn = fixtures.postgres_dsn
objects = publication_fixtures.objects
PATH = "/v1/extensions/skill-packages"
HEADERS = AUTH | {"Content-Type": "application/zip", "Idempotency-Key": "startup-upload"}


@pytest.mark.parametrize("explicit_bundle", [False, True])
def test_normal_cloud_startup_upload_restart_and_install(
    dsn: str, objects: S3ArtifactObjectStore, monkeypatch: pytest.MonkeyPatch,
    explicit_bundle: bool,
) -> None:
    namespace = "skill-startup"
    # Only the fixture-owned bucket/schema are supplied to the real resolver.
    values = {
        "ZEBRA_DATABASE_URL": dsn,
        "ZEBRA_DEPLOYMENT_NAMESPACE": namespace,
        "ZEBRA_MEMORY_CURSOR_SIGNING_KEY": "test-signing-key-" * 3,
        "ZEBRA_AUTHORITY_ISSUER": "https://issuer.example",
        "ZEBRA_HISTORY_SCOPE_NAMESPACE": "history-test",
        "ZEBRA_CONTINUATION_SCOPE_NAMESPACE": "continuation-test",
        "ZEBRA_S3_ENDPOINT": os.environ["ZEBRA_TEST_S3_ENDPOINT"],
        "ZEBRA_S3_ACCESS_KEY": os.environ["ZEBRA_TEST_S3_ACCESS_KEY"],
        "ZEBRA_S3_SECRET_KEY": os.environ["ZEBRA_TEST_S3_SECRET_KEY"],
        "ZEBRA_S3_BUCKET": objects._bucket,
        "ZEBRA_S3_KEY_PREFIX": objects._key_prefix,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("ZEBRA_S3_SESSION_TOKEN", raising=False)
    cloud = cloud_composition_from_environment(values) if explicit_bundle else None
    settings = replace(_cloud_settings(dsn), cloud_extensions_read_enabled=True,
                       cloud_extensions_manage_enabled=True, cloud_skills_publish_enabled=True)
    grant = _verified(scopes=["extensions.read", "extensions.manage"])

    def client(*, other_user: bool = False) -> TestClient:
        return TestClient(create_http_app(
            settings=settings, cloud_composition=cloud,
            host_grant_authorizer=Authorizer(_verified(sub="user-b") if other_user else grant),
        ))

    archive = publication_fixtures._archive("NORMAL-STARTUP-PRIVATE-BODY")
    with client() as first:
        response = first.post(PATH, headers=HEADERS, content=archive)
        assert response.status_code == 200, response.text
        metadata = response.json()
        assert metadata["state"] == "ready"
        location = response.headers["location"]
    publication = asyncio.run(PostgresSkillPublicationStore(
        dsn, deployment_namespace=namespace,
    ).get(scope=extension_scope_from_grant(grant, permission="extensions.read"),
          skill_id=metadata["skill_id"], version_id=metadata["version_id"]))
    assert objects.read_verified(publication.expectation) == archive
    with client() as restarted:
        assert restarted.get(location, headers=AUTH).json() == metadata
        assert restarted.post(PATH, headers=HEADERS, content=archive).json() == metadata
        installed = restarted.post(
            "/v1/extensions/skill-installations", headers=AUTH | {"Idempotency-Key": "install"},
            json={"skill_id": metadata["skill_id"], "version_id": metadata["version_id"]},
        )
        assert installed.status_code == 201, installed.text
        assert installed.json()["enabled"] is False
    with client(other_user=True) as other:
        assert other.get(location, headers=AUTH).status_code == 404
