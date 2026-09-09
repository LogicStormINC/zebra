"""Immutable extension snapshots, using only disposable PostgreSQL schemas."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Generator
from contextlib import nullcontext
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.extension_snapshots import (
    ExtensionPermissions,
    ExtensionSnapshot,
    McpSnapshotEntry,
)
from agent_core.domain.extensions import (
    ExtensionScope,
    McpConnection,
    SkillInstallation,
    SkillVersion,
)
from agent_core.ports.extension_snapshots import (
    ExtensionSnapshotConflictError,
    ExtensionSnapshotIntegrityError,
    ExtensionSnapshotNotFoundError,
)
from agent_storage import apply_postgres_migrations
from agent_storage.postgres.extension_snapshots import PostgresExtensionSnapshotStore
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

SCOPE = ExtensionScope(
    authority_issuer="issuer", namespace_id="tenant", principal_id="user", workspace_id="workspace"
)


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    # Override the business-schema fixture before it can migrate its default schema.
    value = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not value:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return value


@pytest.fixture
def dsn(postgres_dsn: str) -> Generator[str, None, None]:
    schema = f"extension_snapshots_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    try:
        apply_postgres_migrations(isolated)
        yield isolated
    finally:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def _snapshot(scope: ExtensionScope = SCOPE, count: int = 1, **changes: Any) -> ExtensionSnapshot:
    return ExtensionSnapshot(
        scope=scope,
        session_id="session",
        turn_id="turn",
        skills=tuple(
            SkillInstallation(
                scope=scope,
                installation_id=f"install-{i}",
                revision=1,
                version=SkillVersion(
                    skill_id=f"skill-{i}",
                    version_id="v1",
                    artifact_ref="artifact://test",
                    content_digest="a" * 64,
                ),
            )
            for i in range(count)
        ),
        mcp=tuple(
            McpSnapshotEntry(
                connection=McpConnection(
                    scope=scope,
                    connection_id=f"mcp-{i}",
                    revision=1,
                    endpoint="https://mcp.example/api",
                ),
                catalog_digest="b" * 64,
                permissions=ExtensionPermissions(tools=("read",)),
            )
            for i in range(count)
        ),
    ).model_copy(update=changes)


async def _get(
    store: PostgresExtensionSnapshotStore, snapshot: ExtensionSnapshot
) -> ExtensionSnapshot:
    return await store.get(
        scope=snapshot.scope,
        session_id=snapshot.session_id,
        turn_id=snapshot.turn_id,
        expected_digest=snapshot.digest,
    )


def test_replay_restart_and_trusted_digest(dsn: str) -> None:
    store = PostgresExtensionSnapshotStore(dsn, deployment_namespace="cloud")
    fresh = PostgresExtensionSnapshotStore(dsn, deployment_namespace="cloud")
    snapshot = _snapshot()

    async def check() -> None:
        assert not await store.exists(scope=SCOPE, session_id="session", turn_id="turn")
        await store.save(scope=SCOPE, snapshot=snapshot)
        await fresh.save(scope=SCOPE, snapshot=snapshot)
        assert await _get(fresh, snapshot) == snapshot
        assert await fresh.exists(scope=SCOPE, session_id="session", turn_id="turn")
        with pytest.raises(ExtensionSnapshotIntegrityError):
            await fresh.get(
                scope=SCOPE, session_id="session", turn_id="turn", expected_digest="f" * 64
            )
        with store.connect() as connection:
            assert connection.execute(
                "SELECT count(*) AS n FROM turn_extension_snapshots"
            ).fetchone() == {"n": 1}

    asyncio.run(check())


@pytest.mark.parametrize("change", ["identical", "version", "permissions"])
def test_concurrent_immutable_writes(dsn: str, change: str) -> None:
    store = PostgresExtensionSnapshotStore(dsn, deployment_namespace="cloud")
    original = _snapshot()
    payload = original.model_dump()
    if change == "version":
        payload["skills"][0]["version"]["version_id"] = "v2"
    elif change == "permissions":
        payload["mcp"][0]["permissions"]["tools"] = ("write",)
    alternative = ExtensionSnapshot.model_validate(payload)

    async def check() -> None:
        results = await asyncio.gather(
            store.save(scope=SCOPE, snapshot=original),
            store.save(scope=SCOPE, snapshot=alternative),
            return_exceptions=True,
        )
        assert sum(value is None for value in results) == (2 if change == "identical" else 1)
        assert sum(isinstance(value, ExtensionSnapshotConflictError) for value in results) == (
            0 if change == "identical" else 1
        )
        winner = original if results[0] is None else alternative
        assert await _get(store, winner) == winner

    asyncio.run(check())


@pytest.mark.parametrize(
    "field",
    [
        "deployment",
        "authority_issuer",
        "namespace_id",
        "principal_id",
        "workspace_id",
        "session_id",
        "turn_id",
    ],
)
def test_all_coordinates_isolated(dsn: str, field: str) -> None:
    store = PostgresExtensionSnapshotStore(dsn, deployment_namespace="cloud")
    other = PostgresExtensionSnapshotStore(
        dsn, deployment_namespace=("other" if field == "deployment" else "cloud")
    )
    original = _snapshot()
    scope = (
        SCOPE
        if field in ("deployment", "session_id", "turn_id")
        else (SCOPE.model_copy(update={field: "other"}))
    )
    snapshot = _snapshot(scope, **({field: "other"} if field in ("session_id", "turn_id") else {}))

    async def check() -> None:
        await store.save(scope=SCOPE, snapshot=original)
        with pytest.raises(ExtensionSnapshotNotFoundError):
            await _get(other, snapshot)
        await other.save(scope=scope, snapshot=snapshot)
        assert await _get(other, snapshot) == snapshot
        assert await _get(store, original) == original

    asyncio.run(check())


def test_maximum_unicode_coordinates_and_entry_counts(dsn: str) -> None:
    opaque = "".join(chr(0x10000 + i) for i in range(512))
    scope = ExtensionScope(
        authority_issuer=opaque, namespace_id=opaque[:255], principal_id=opaque, workspace_id=opaque
    )
    snapshot = _snapshot(scope, 32, session_id=opaque, turn_id=opaque)
    store = PostgresExtensionSnapshotStore(dsn, deployment_namespace=opaque[:255])

    async def check() -> None:
        await store.save(scope=scope, snapshot=snapshot)
        assert await _get(store, snapshot) == snapshot

    asyncio.run(check())


@pytest.mark.parametrize(
    "field,value",
    [
        ("session_id", " "),
        ("turn_id", "bad\x00id"),
        ("turn_id", "x" * 513),
        ("expected_digest", "A" * 64),
        ("expected_digest", 123),
        ("session_id", True),
        ("scope", {}),
        ("scope", SCOPE.model_copy(update={"principal_id": " "})),
    ],
)
def test_invalid_get_before_database(
    field: str, value: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PostgresExtensionSnapshotStore("host=invalid", deployment_namespace="cloud")
    monkeypatch.setattr(store, "connect", lambda: pytest.fail("invalid input opened database"))
    values = dict(scope=SCOPE, session_id="session", turn_id="turn", expected_digest="a" * 64)
    values[field] = value
    with pytest.raises((TypeError, ValueError)):
        asyncio.run(store.get(**values))


@pytest.mark.parametrize("kind", ["dict", "scope", "session", "nested", "skills", "mcp"])
def test_invalid_save_before_database(kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    store = PostgresExtensionSnapshotStore("host=invalid", deployment_namespace="cloud")
    monkeypatch.setattr(store, "connect", lambda: pytest.fail("invalid input opened database"))
    snapshot: Any = _snapshot()
    if kind == "dict":
        snapshot = snapshot.model_dump()
    elif kind == "scope":
        snapshot = _snapshot(SCOPE.model_copy(update={"principal_id": "other"}))
    elif kind == "session":
        snapshot = snapshot.model_copy(update={"session_id": False})
    elif kind == "nested":
        skill = snapshot.skills[0].model_copy(update={"enabled": False})
        snapshot = snapshot.model_copy(update={"skills": (skill,)})
    else:
        entries = getattr(_snapshot(count=32), kind)
        snapshot = snapshot.model_copy(update={kind: (*entries, entries[0])})
    warning = (
        pytest.warns(UserWarning, match="Pydantic serializer warnings")
        if kind == "session"
        else nullcontext()
    )
    with warning, pytest.raises((TypeError, ValueError)):
        asyncio.run(store.save(scope=SCOPE, snapshot=snapshot))


@pytest.mark.parametrize(
    "drift",
    [
        "scope",
        "session_id",
        "turn_id",
        "schema",
        "digest",
        "payload",
        "payload_and_digest",
    ],
)
def test_tampering_fails_closed(dsn: str, drift: str) -> None:
    store = PostgresExtensionSnapshotStore(dsn, deployment_namespace="cloud")
    original = _snapshot()
    asyncio.run(store.save(scope=SCOPE, snapshot=original))
    payload = original.model_dump(mode="json")
    stored_digest = original.digest
    if drift == "scope":
        payload["scope"]["principal_id"] = "other"
    elif drift in ("session_id", "turn_id"):
        payload[drift] = "other"
    elif drift == "schema":
        payload["unexpected"] = True
    elif drift == "digest":
        stored_digest = "f" * 64
    else:
        payload["mcp"][0]["permissions"]["tools"] = ["write"]
        if drift == "payload_and_digest":
            stored_digest = ExtensionSnapshot.model_validate(payload).digest
    with store.connect() as connection:
        connection.execute(
            "UPDATE turn_extension_snapshots SET payload = %s, snapshot_digest = %s",
            (Jsonb(payload), stored_digest),
        )
    with pytest.raises(ExtensionSnapshotIntegrityError):
        asyncio.run(_get(store, original))
    # A coherently replaced payload is a conflicting write; trusted digest still rejects reads.
    error = (
        ExtensionSnapshotConflictError
        if drift == "payload_and_digest"
        else ExtensionSnapshotIntegrityError
    )
    with pytest.raises(error):
        asyncio.run(store.save(scope=SCOPE, snapshot=original))
