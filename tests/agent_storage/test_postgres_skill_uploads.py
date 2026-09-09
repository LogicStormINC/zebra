"""Upload keys and immutable publications commit together in PostgreSQL."""

import asyncio

import pytest
from agent_core.ports.skill_publications import SkillPublicationConflictError
from agent_storage.postgres.skill_publications import PostgresSkillPublicationStore
from agent_tools.skill_publications import _candidate, publish_skill_package

from tests.agent_storage import test_postgres_extensions as fixtures
from tests.agent_tools.test_skill_publications import SCOPE, Objects, archive

postgres_dsn = fixtures.postgres_dsn
dsn = fixtures.dsn


def test_concurrent_keys_restart_and_rollback(dsn: str) -> None:
    store = PostgresSkillPublicationStore(dsn, deployment_namespace="test")
    data = archive()
    candidate = _candidate(data, SCOPE, "test")

    async def check() -> None:
        results = await asyncio.gather(*(store.reserve(
            scope=SCOPE, publication=candidate, idempotency_key="one",
        ) for _ in range(5)))
        assert results == [candidate] * 5
        fresh = PostgresSkillPublicationStore(dsn, deployment_namespace="test")
        for changed in (archive("changed"), archive(version="v2")):
            with pytest.raises(SkillPublicationConflictError):
                await fresh.reserve(scope=SCOPE, publication=_candidate(changed, SCOPE, "test"),
                                    idempotency_key="one")
        with pytest.raises(SkillPublicationConflictError):
            await fresh.reserve(scope=SCOPE, publication=_candidate(archive("changed"), SCOPE,
                                                                   "test"), idempotency_key="two")
        assert await fresh.reserve(scope=SCOPE, publication=candidate,
                                   idempotency_key="two") == candidate
        with fresh.connect() as connection:
            assert connection.execute("SELECT count(*) AS n FROM skill_package_upload_keys"
                                      ).fetchone()["n"] == 2
            assert connection.execute("SELECT count(*) AS n FROM skill_package_versions"
                                      ).fetchone()["n"] == 1
    asyncio.run(check())


@pytest.mark.parametrize("field", ["authority_issuer", "namespace_id", "principal_id",
                                   "workspace_id", "deployment"])
def test_keys_are_exact_scope_and_deployment(dsn: str, field: str) -> None:
    store = PostgresSkillPublicationStore(dsn, deployment_namespace="test")
    other_scope = SCOPE if field == "deployment" else SCOPE.model_copy(update={field: "other"})
    other = PostgresSkillPublicationStore(
        dsn, deployment_namespace="other" if field == "deployment" else "test",
    )
    async def check() -> None:
        await store.reserve(scope=SCOPE, publication=_candidate(archive(), SCOPE, "test"),
                            idempotency_key="one")
        candidate = _candidate(archive("different"), other_scope, other.deployment_namespace)
        assert await other.reserve(scope=other_scope, publication=candidate,
                                   idempotency_key="one") == candidate
    asyncio.run(check())


def test_object_failure_resumes_same_key_and_ready_preserves_receipt(dsn: str) -> None:
    objects = Objects()
    objects.fail = True
    data = archive()
    async def publish() -> object:
        return await publish_skill_package(
            archive=data, scope=SCOPE, deployment_namespace="test", idempotency_key="one",
            store=PostgresSkillPublicationStore(dsn, deployment_namespace="test"), objects=objects,
        )
    with pytest.raises(RuntimeError):
        asyncio.run(publish())
    objects.fail = False
    ready = asyncio.run(publish())
    assert ready.state == "ready"
    assert asyncio.run(publish()) == ready
    assert objects.calls == 2
