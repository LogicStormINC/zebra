"""Real PostgreSQL reservations use an exclusively disposable schema."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from agent_core.domain.artifact_objects import ArtifactObjectReceipt
from agent_core.domain.extensions import ExtensionScope
from agent_core.ports.skill_publications import (
    SkillPublicationConflictError,
    SkillPublicationNotFoundError,
)
from agent_storage.postgres.skill_publications import PostgresSkillPublicationStore
from agent_tools.skill_publications import _candidate, publish_skill_package
from psycopg.types.json import Jsonb

from tests.agent_storage import test_postgres_extensions as fixtures
from tests.agent_tools.test_skill_publications import SCOPE, Objects, archive

postgres_dsn = fixtures.postgres_dsn
dsn = fixtures.dsn


def test_concurrent_reservation_and_immutable_conflict(dsn: str) -> None:
    store = PostgresSkillPublicationStore(dsn, deployment_namespace="test")
    candidate = _candidate(archive(), SCOPE, "test")

    async def check() -> None:
        results = await asyncio.gather(*(store.reserve(scope=SCOPE, publication=candidate)
                                         for _ in range(5)))
        assert results == [candidate] * 5
        for data in (archive("changed"), archive(comment=b"repack")):
            with pytest.raises(SkillPublicationConflictError):
                await store.reserve(scope=SCOPE, publication=_candidate(data, SCOPE, "test"))
    asyncio.run(check())


@pytest.mark.parametrize("field", ["authority_issuer", "namespace_id", "principal_id",
                                   "workspace_id", "deployment"])
def test_exact_scope_isolation(dsn: str, field: str) -> None:
    store = PostgresSkillPublicationStore(dsn, deployment_namespace="test")
    candidate = _candidate(archive(), SCOPE, "test")
    other_scope = SCOPE if field == "deployment" else ExtensionScope.model_validate({
        **SCOPE.model_dump(), field: "other",
    })
    other = PostgresSkillPublicationStore(
        dsn, deployment_namespace="other" if field == "deployment" else "test",
    )

    async def check() -> None:
        await store.reserve(scope=SCOPE, publication=candidate)
        with pytest.raises(SkillPublicationNotFoundError):
            await other.get(scope=other_scope, skill_id=candidate.version.skill_id,
                            version_id=candidate.version.version_id)
        second = _candidate(archive(), other_scope, other.deployment_namespace)
        assert await other.reserve(scope=other_scope, publication=second) == second
    asyncio.run(check())


def test_fresh_store_resumes_after_object_written_before_ready(dsn: str) -> None:
    class Failing(PostgresSkillPublicationStore):
        async def mark_ready(self, **kwargs: object) -> object:
            raise RuntimeError("interrupted before ready")
    objects = Objects()
    data = archive()
    store = Failing(dsn, deployment_namespace="test")
    with pytest.raises(RuntimeError):
        asyncio.run(publish_skill_package(archive=data, scope=SCOPE,
                    deployment_namespace="test", store=store, objects=objects))
    fresh = PostgresSkillPublicationStore(dsn, deployment_namespace="test")
    ready = asyncio.run(publish_skill_package(archive=data, scope=SCOPE,
                        deployment_namespace="test", store=fresh, objects=objects))
    assert ready.state == "ready" and objects.calls == 2
    assert asyncio.run(fresh.get(scope=SCOPE, skill_id=ready.version.skill_id,
                                version_id=ready.version.version_id)) == ready


def test_malformed_metadata_fails_closed(dsn: str) -> None:
    store = PostgresSkillPublicationStore(dsn, deployment_namespace="test")
    candidate = _candidate(archive(), SCOPE, "test")
    asyncio.run(store.reserve(scope=SCOPE, publication=candidate))
    with store.connect() as connection:
        connection.execute("UPDATE skill_package_versions SET payload = %s",
                           (Jsonb({**candidate.model_dump(mode="json"), "name": "foreign"}),))
    with pytest.raises(ValueError):
        asyncio.run(store.get(scope=SCOPE, skill_id=candidate.version.skill_id,
                              version_id=candidate.version.version_id))


def test_deployment_mismatch_rejected_before_connection() -> None:
    store = PostgresSkillPublicationStore("unreachable", deployment_namespace="test")
    with pytest.raises(ValueError, match="trusted storage scope"):
        asyncio.run(store.reserve(scope=SCOPE, publication=_candidate(archive(), SCOPE, "other")))


def test_concurrent_conflicting_versions_choose_one_immutable_candidate(dsn: str) -> None:
    store = PostgresSkillPublicationStore(dsn, deployment_namespace="test")
    candidates = [_candidate(archive(body), SCOPE, "test") for body in ("first", "second")]

    async def check() -> None:
        results = await asyncio.gather(*(store.reserve(scope=SCOPE, publication=candidate)
                                        for candidate in candidates), return_exceptions=True)
        assert sum(isinstance(result, SkillPublicationConflictError) for result in results) == 1
        saved = await store.get(scope=SCOPE, skill_id=candidates[0].version.skill_id,
                                version_id=candidates[0].version.version_id)
        assert saved in candidates and saved in results
    asyncio.run(check())


def test_ready_receipt_preserves_version_and_first_verification(dsn: str) -> None:
    store = PostgresSkillPublicationStore(dsn, deployment_namespace="test")
    candidate = _candidate(archive(), SCOPE, "test")
    receipt = ArtifactObjectReceipt(expectation=candidate.expectation, object_version="first",
                                    verified_at=datetime.now(UTC))
    key = {"scope": SCOPE, "skill_id": candidate.version.skill_id,
           "version_id": candidate.version.version_id}

    async def check() -> None:
        await store.reserve(scope=SCOPE, publication=candidate)
        first = await store.mark_ready(**key, receipt=receipt)
        later = receipt.model_copy(update={
            "verified_at": receipt.verified_at + timedelta(seconds=1),
        })
        assert await store.mark_ready(**key, receipt=later) == first
        assert first.receipt == receipt
        with pytest.raises(ValueError, match="ready object version"):
            await store.mark_ready(**key, receipt=receipt.model_copy(
                update={"object_version": "different"},
            ))
        assert await store.get(**key) == first
    asyncio.run(check())
