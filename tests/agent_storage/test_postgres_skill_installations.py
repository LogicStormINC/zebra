"""Skill installation acceptance in disposable schemas, never business data."""

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from agent_core.application.extension_configuration import set_extension_enabled
from agent_core.application.skill_installations import create_skill_installation
from agent_core.ports.extensions import ExtensionNotFoundError, ExtensionRevisionConflictError
from agent_security.extension_authority import extension_scope_from_grant
from agent_storage import sqlite_control_plane_stores
from agent_storage.postgres.extensions import PostgresExtensionStore
from agent_storage.postgres.skill_publications import PostgresSkillPublicationStore
from agent_tools.skill_publications import _candidate, publish_skill_package
from fastapi.testclient import TestClient
from zebra_agent_api import create_http_app

from tests.agent_security.test_extension_authority import _verified
from tests.agent_storage import test_postgres_extensions as fixtures
from tests.agent_tools.test_skill_publications import Objects, archive
from tests.api.test_extension_reads import AUTH, Authorizer
from tests.api.test_host_auth_http import _cloud_settings

postgres_dsn = fixtures.postgres_dsn
dsn = fixtures.dsn
SCOPE = fixtures.SCOPE
PATH = "/v1/extensions/skill-installations"
HEADERS = AUTH | {"Idempotency-Key": "install-one"}


def test_concurrent_install_and_restart_replay(dsn: str) -> None:
    store = PostgresExtensionStore(dsn, deployment_namespace="cloud-a")
    fresh = PostgresExtensionStore(dsn, deployment_namespace="cloud-a")

    async def check() -> None:
        published = await publish_skill_package(
            archive=archive(), scope=SCOPE, deployment_namespace="cloud-a",
            store=PostgresSkillPublicationStore(dsn, deployment_namespace="cloud-a"),
            objects=Objects(),
        )
        payload = {"skill_id": published.version.skill_id,
                   "version_id": published.version.version_id}
        results = await asyncio.gather(*(
            create_skill_installation(store=adapter, scope=SCOPE,
                                      idempotency_key="one", payload=payload)
            for adapter in (store, fresh, store, fresh)
        ))
        assert sum(created for _, created in results) == 1
        original = results[0][0]
        assert not original.enabled and original.version == published.version
        assert all(record == original for record, _ in results)
        current = await set_extension_enabled(
            store=store, scope=SCOPE, kind="skill", object_id=original.installation_id,
            expected_revision=1, enabled=True,
        )
        replay, created = await create_skill_installation(
            store=fresh, scope=SCOPE, idempotency_key="one", payload=payload,
        )
        assert not created and replay == current
        with pytest.raises(ExtensionRevisionConflictError):
            await create_skill_installation(
                store=fresh, scope=SCOPE, idempotency_key="one",
                payload=payload | {"version_id": "unknown"},
            )
        with store.connect() as connection:
            assert connection.execute(
                "SELECT count(*) AS count FROM extension_configuration_revisions"
            ).fetchone() == {"count": 2}

    asyncio.run(check())


@pytest.mark.parametrize("coordinate", [
    "authority_issuer", "namespace_id", "principal_id", "workspace_id", "deployment",
])
def test_install_cannot_use_another_owner_publication(dsn: str, coordinate: str) -> None:
    async def check() -> None:
        published = await publish_skill_package(
            archive=archive(), scope=SCOPE, deployment_namespace="cloud-a",
            store=PostgresSkillPublicationStore(dsn, deployment_namespace="cloud-a"),
            objects=Objects(),
        )
        scope = SCOPE if coordinate == "deployment" else SCOPE.model_copy(
            update={coordinate: "other"},
        )
        store = PostgresExtensionStore(
            dsn, deployment_namespace="cloud-b" if coordinate == "deployment" else "cloud-a",
        )
        with pytest.raises(ExtensionNotFoundError):
            await create_skill_installation(
                store=store, scope=scope, idempotency_key="one",
                payload={"skill_id": published.version.skill_id,
                         "version_id": published.version.version_id},
            )
        with store.connect() as connection:
            assert connection.execute(
                "SELECT count(*) AS count FROM extension_configurations"
            ).fetchone() == {"count": 0}

    asyncio.run(check())


def test_http_pending_publish_install_get_toggle_replay(dsn: str, tmp_path: Path) -> None:
    grant = _verified(scopes=["extensions.read", "extensions.manage"])
    scope = extension_scope_from_grant(grant, permission="extensions.manage")
    publications = PostgresSkillPublicationStore(dsn, deployment_namespace="cloud-a")
    data = archive()
    candidate = _candidate(data, scope, "cloud-a")
    asyncio.run(publications.reserve(scope=scope, publication=candidate))
    payload = {"skill_id": candidate.version.skill_id, "version_id": candidate.version.version_id}
    database = tmp_path / "http.sqlite"
    with TestClient(create_http_app(
        database, settings=replace(_cloud_settings(dsn), cloud_extensions_manage_enabled=True),
        stores=sqlite_control_plane_stores(database),
        extension_store=PostgresExtensionStore(dsn, deployment_namespace="cloud-a"),
        host_grant_authorizer=Authorizer(grant),
    )) as client:
        assert client.post(PATH, headers=HEADERS, json=payload).status_code == 404
        asyncio.run(publish_skill_package(
            archive=data, scope=scope, deployment_namespace="cloud-a",
            store=publications, objects=Objects(),
        ))
        first = client.post(PATH, headers=HEADERS, json=payload)
        assert first.status_code == 201 and first.json()["enabled"] is False
        assert "artifact_ref" not in first.text and "scope" not in first.text
        location = first.headers["location"]
        assert client.get(location, headers=AUTH).json() == first.json()
        changed = client.patch(location, headers=AUTH | {"If-Match": '"1"'},
                               json={"enabled": True})
        assert changed.status_code == 200 and changed.headers["etag"] == '"2"'
        replay = client.post(PATH, headers=HEADERS, json=payload)
        assert replay.status_code == 200 and replay.json() == changed.json()
        assert replay.headers["etag"] == '"2"'
