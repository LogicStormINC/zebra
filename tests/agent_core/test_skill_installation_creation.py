import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from agent_core.application.skill_installations import create_skill_installation
from agent_core.domain.artifact_objects import ArtifactObjectReceipt
from agent_core.domain.skill_publications import SkillPublication
from agent_core.ports.extensions import (
    ExtensionNotFoundError,
    ExtensionRevisionConflictError,
    ExtensionStore,
)
from agent_tools.skill_publications import _candidate
from pydantic import ValidationError

from tests.agent_tools.test_skill_publications import archive
from tests.api.test_extension_reads import SCOPE


def publication() -> SkillPublication:
    candidate = _candidate(archive(), SCOPE, "test")
    return SkillPublication.model_validate(candidate.model_dump() | {
        "state": "ready", "receipt": ArtifactObjectReceipt(
            expectation=candidate.expectation, object_version="1", verified_at=datetime.now(UTC),
        ),
    })


def installation_store() -> AsyncMock:
    store = AsyncMock(spec=ExtensionStore)
    store.get_skill_creation.side_effect = ExtensionNotFoundError()
    store.get_skill_publication.return_value = publication()
    return store


def payload(store: AsyncMock) -> dict[str, str]:
    version = store.get_skill_publication.return_value.version
    return {"skill_id": version.skill_id, "version_id": version.version_id}


def test_creation_and_replay_current_after_toggle() -> None:
    store = installation_store()
    request = payload(store)

    async def check() -> None:
        original, created = await create_skill_installation(
            store=store, scope=SCOPE, idempotency_key="key", payload=request,
        )
        assert created and not original.enabled and original.revision == 1
        assert original.version == store.get_skill_publication.return_value.version
        assert store.save_skill.await_args.kwargs["expected_revision"] is None
        store.get_skill_creation.side_effect = None
        store.get_skill_creation.return_value = original
        current = original.model_copy(update={"enabled": True, "revision": 2})
        store.get_skill.return_value = current
        replay, created = await create_skill_installation(
            store=store, scope=SCOPE, idempotency_key="key", payload=request,
        )
        assert replay == current and not created
        for field in ("skill_id", "version_id"):
            with pytest.raises(ExtensionRevisionConflictError):
                await create_skill_installation(
                    store=store, scope=SCOPE, idempotency_key="key",
                    payload=request | {field: "unknown"},
                )
        assert store.get_skill_publication.await_count == store.save_skill.await_count == 1

    asyncio.run(check())


def test_concurrent_collision_replays_winner() -> None:
    store = installation_store()

    async def collide(**kwargs: object) -> None:
        store.get_skill_creation.side_effect = None
        store.get_skill_creation.return_value = kwargs["installation"]
        store.get_skill.return_value = kwargs["installation"]
        raise ExtensionRevisionConflictError()

    store.save_skill.side_effect = collide
    record, created = asyncio.run(create_skill_installation(
        store=store, scope=SCOPE, idempotency_key="key", payload=payload(store),
    ))
    assert not created and record.revision == 1


@pytest.mark.parametrize("key", ["", "x" * 129, "has space", "\n", "\x7f", "é", 3, None])
def test_key_before_storage(key: object) -> None:
    store = installation_store()
    with pytest.raises(ValidationError):
        asyncio.run(create_skill_installation(
            store=store, scope=SCOPE, idempotency_key=key, payload=payload(store),  # type: ignore[arg-type]
        ))
    assert not store.mock_calls


@pytest.mark.parametrize("change", ["publishing", "foreign", "wrong-version", "corrupt", "type"])
def test_publication_fails_closed(change: str) -> None:
    store = installation_store()
    request = payload(store)
    original = store.get_skill_publication.return_value
    if change == "publishing":
        altered = original.model_copy(update={"state": "publishing", "receipt": None})
    elif change == "foreign":
        altered = _candidate(archive(), SCOPE.model_copy(update={"principal_id": "other"}), "test")
    elif change == "wrong-version":
        altered = _candidate(archive(version="v2"), SCOPE, "test")
    elif change == "corrupt":
        altered = original.model_copy(update={"manifest": ()})
    else:
        altered = None
    store.get_skill_publication.return_value = altered
    with pytest.raises(RuntimeError if change in ("corrupt", "type") else ExtensionNotFoundError):
        asyncio.run(create_skill_installation(
            store=store, scope=SCOPE, idempotency_key="key", payload=request,
        ))
    store.save_skill.assert_not_awaited()
