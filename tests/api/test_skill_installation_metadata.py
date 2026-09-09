"""Installed Skill metadata is public only within its exact publication scope."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from agent_core.domain.extensions import SkillInstallation
from agent_core.ports.extensions import ExtensionStore, SkillInstallationPage
from agent_core.ports.skill_publications import (
    SkillPublicationNotFoundError,
    SkillPublicationStorePort,
)
from agent_tools.skill_publications import SkillPublicationService, publish_skill_package
from starlette.requests import Request
from zebra_agent_api.extension_reads import extension_read_response

from tests.agent_tools.test_skill_publications import Objects, Store, archive
from tests.api.test_extension_reads import SCOPE, VERIFIED


@pytest.mark.parametrize("detail", [False, True])
@pytest.mark.parametrize("mode", ["ready", "missing", "foreign", "digest", "failure"])
def test_metadata_is_scoped_and_legacy_installations_stay_manageable(detail, mode):
    async def run():
        objects = Objects()
        publication = await publish_skill_package(
            archive=archive(), scope=SCOPE, deployment_namespace="test",
            store=Store(), objects=objects,
        )
        record = SkillInstallation(scope=SCOPE, installation_id="installed", revision=1,
                                   version=publication.version)
        if mode == "digest":
            record = record.model_copy(update={"version": record.version.model_copy(
                update={"content_digest": "b" * 64},
            )})
        publications = AsyncMock(spec=SkillPublicationStorePort)
        publications.get.return_value = publication
        if mode == "missing":
            publications.get.side_effect = SkillPublicationNotFoundError()
        elif mode == "foreign":
            publications.get.return_value = publication.model_copy(update={
                "scope": SCOPE.model_copy(update={"principal_id": "someone-else"}),
            })
        elif mode == "failure":
            publications.get.side_effect = RuntimeError("database unavailable")
        store = AsyncMock(spec=ExtensionStore)
        store.get_skill.return_value = record
        store.list_skills.return_value = SkillInstallationPage(items=(record,), next_cursor=None)
        path = "/v1/extensions/skill-installations" + ("/installed" if detail else "")
        request = Request({"type": "http", "method": "GET", "path": path,
                           "headers": [], "query_string": b""})
        request.state.verified_host_grant = VERIFIED
        response = await extension_read_response(request, store=store, deployment="cloud",
            publications=SkillPublicationService(publications, objects, "test"))
        assert response is not None
        if mode in {"failure", "foreign"}:
            assert response.status_code == 503
            return
        assert response.status_code == 200
        body = json.loads(response.body)
        item = body if detail else body["items"][0]
        assert item["installation_id"] == "installed"
        if mode == "ready":
            assert (item["name"], item["description"], item["version_label"]) == (
                "sample", "Sample", "v1",
            )
        else:
            assert "name" not in item and "description" not in item
        assert "artifact_ref" not in str(item) and "someone-else" not in str(item)
        publications.get.assert_awaited_once_with(scope=SCOPE, skill_id=record.version.skill_id,
                                                 version_id=record.version.version_id)
    asyncio.run(run())
