"""HTTP upload recovery through real PG and MinIO in disposable test resources."""

import asyncio
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

from agent_core.domain.extension_snapshots import ExtensionSnapshot
from agent_core.ports.skill_publications import SkillPublicationStorePort
from agent_security.extension_authority import extension_scope_from_grant
from agent_storage import sqlite_control_plane_stores
from agent_storage.artifact_objects import S3ArtifactObjectStore
from agent_storage.postgres.extensions import PostgresExtensionStore
from agent_storage.postgres.skill_publications import PostgresSkillPublicationStore
from agent_tools.cloud_skills import prepare_cloud_skill_catalog
from agent_tools.skill_publications import SkillPublicationService
from agent_tools.skills import SkillsReadTool
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app

from tests.agent_security.test_extension_authority import _verified
from tests.agent_storage import test_postgres_extensions as fixtures
from tests.agent_storage import test_skill_publication_minio as publication_fixtures
from tests.agent_tools.test_skills import _call
from tests.api.test_extension_reads import AUTH, Authorizer
from tests.api.test_host_auth_http import _cloud_settings

dsn = fixtures.dsn
postgres_dsn = fixtures.postgres_dsn
objects = publication_fixtures.objects
PATH = "/v1/extensions/skill-packages"
HEADERS = AUTH | {"Content-Type": "application/zip", "Idempotency-Key": "upload-one"}


def test_http_upload_interruption_replay_install_and_private_tool_read(
    dsn: str, objects: S3ArtifactObjectStore, tmp_path: Path,
) -> None:
    namespace = "cloud-a"
    publications = PostgresSkillPublicationStore(dsn, deployment_namespace=namespace)
    interrupted = AsyncMock(spec=SkillPublicationStorePort, wraps=publications)
    interrupted.mark_ready.side_effect = RuntimeError("private failure detail")
    service = SkillPublicationService(
        store=interrupted, objects=objects, deployment_namespace=namespace,
    )
    extensions = PostgresExtensionStore(dsn, deployment_namespace=namespace)
    grant = _verified(scopes=["extensions.read", "extensions.manage"])
    scope = extension_scope_from_grant(grant, permission="extensions.manage")
    database = tmp_path / "http.sqlite"
    settings = replace(_cloud_settings(dsn), cloud_extensions_read_enabled=True,
                       cloud_extensions_manage_enabled=True)

    def app(service: SkillPublicationService, *, other_user: bool = False) -> TestClient:
        return TestClient(create_http_app(
            database, settings=settings, stores=sqlite_control_plane_stores(database),
            extension_store=extensions, skill_publication_service=service,
            host_grant_authorizer=Authorizer(
                _verified(sub="user-b") if other_user else grant,
            ),
        ))

    data = publication_fixtures._archive("PRIVATE-UPLOAD-A")
    with app(service) as client:
        failed = client.post(PATH, headers=HEADERS, content=data)
        assert failed.status_code == 503 and "private failure" not in failed.text
    candidate = interrupted.reserve.await_args.kwargs["publication"]
    pending = asyncio.run(publications.get(
        scope=scope, skill_id=candidate.version.skill_id, version_id=candidate.version.version_id,
    ))
    assert pending.state == "publishing"
    assert objects.read_verified(pending.expectation) == data

    fresh = SkillPublicationService(
        store=PostgresSkillPublicationStore(dsn, deployment_namespace=namespace),
        objects=objects, deployment_namespace=namespace,
    )
    with app(fresh) as client:
        uploaded = client.post(PATH, headers=HEADERS, content=data)
        assert uploaded.status_code == 200 and uploaded.json()["state"] == "ready"
        assert all(secret not in uploaded.text for secret in (
            "artifact://", "receipt", "workspace_id", "PRIVATE-UPLOAD-A",
        ))
        location = uploaded.headers["location"]
        assert client.get(location, headers=AUTH).json() == uploaded.json()
        assert client.post(PATH, headers=HEADERS, content=data).json() == uploaded.json()
        assert client.post(PATH, headers=HEADERS, content=publication_fixtures._archive(
            "CHANGED-CONTENT",
        )).status_code == 409
        version = uploaded.json()
        installed = client.post(
            "/v1/extensions/skill-installations", headers=AUTH | {"Idempotency-Key": "install"},
            json={"skill_id": version["skill_id"], "version_id": version["version_id"]},
        )
        assert installed.status_code == 201
        enabled = client.patch(installed.headers["location"],
                               headers=AUTH | {"If-Match": '"1"'}, json={"enabled": True})
        assert enabled.status_code == 200
        installation = asyncio.run(extensions.get_skill(
            scope=scope, installation_id=installed.json()["installation_id"],
        ))
        catalog = asyncio.run(prepare_cloud_skill_catalog(
            snapshot=ExtensionSnapshot(scope=scope, session_id="session", turn_id="turn",
                                       skills=(installation,)),
            scope=scope, deployment_namespace=namespace, session_id="session", turn_id="turn",
            store=extensions, objects=objects,
        ))
        assert "PRIVATE-UPLOAD-A" in SkillsReadTool(catalog).handle(
            _call("skills.read", {"name": "sample"}),
        ).output
    with app(fresh, other_user=True) as other:
        assert other.get(location, headers=AUTH).status_code == 404
        own = other.post(PATH, headers=HEADERS,
                         content=publication_fixtures._archive("PRIVATE-UPLOAD-B"))
        assert own.status_code == 200 and own.json()["state"] == "ready"
        assert own.json()["content_digest"] != uploaded.json()["content_digest"]
