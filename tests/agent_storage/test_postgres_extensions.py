"""Extension config acceptance against an exclusively disposable PostgreSQL schema."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Generator
from typing import Any, Literal, cast
from unittest.mock import MagicMock
from uuid import uuid4

import psycopg
import pytest
from agent_core.application.extension_configuration import set_extension_enabled
from agent_core.domain.extensions import (
    ExtensionScope,
    McpConnection,
    SkillInstallation,
    SkillVersion,
)
from agent_core.ports.extensions import (
    ExtensionNotFoundError,
    ExtensionPageRequest,
    ExtensionRevisionConflictError,
    ExtensionSkillConflictError,
)
from agent_storage import apply_postgres_migrations
from agent_storage.postgres.extensions import (
    ExtensionSnapshotAdmissionConflictError,
    PostgresExtensionStore,
    _skill_lock_key,
    validate_skill_snapshot_in_transaction,
)
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

from tests.agent_tools.test_cloud_skills import SCOPE as CLOUD_SCOPE
from tests.agent_tools.test_cloud_skills import Backend

SCOPE = ExtensionScope(
    authority_issuer="https://issuer.example",
    namespace_id="tenant-a",
    principal_id="user-a",
    workspace_id="workspace-a",
)


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    # Override the shared fixture: never apply migrations to its default schema.
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def dsn(postgres_dsn: str) -> Generator[str, None, None]:
    schema = f"extensions_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    try:
        apply_postgres_migrations(isolated)
        yield isolated
    finally:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture(params=["skill", "mcp"])
def kind(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def _record(kind: str, identifier: str = "config-a", **updates: Any) -> Any:
    values = {"scope": SCOPE, "revision": 1, **updates}
    if kind == "skill":
        return SkillInstallation(
            installation_id=identifier,
            version=SkillVersion(
                skill_id="skill",
                version_id="v1",
                artifact_ref="artifact://skill-v1",
                content_digest="a" * 64,
            ),
            **values,
        )
    return McpConnection(connection_id=identifier, endpoint="https://mcp.example/api", **values)


def _skill(identifier: str, skill_id: str, **updates: Any) -> SkillInstallation:
    return SkillInstallation(
        scope=SCOPE,
        installation_id=identifier,
        revision=1,
        version=SkillVersion(
            skill_id=skill_id,
            version_id="v1",
            artifact_ref=f"artifact://{skill_id}-v1",
            content_digest="a" * 64,
        ),
        **updates,
    )


def _snapshot_row(record: SkillInstallation) -> dict[str, Any]:
    return {
        "object_id": record.installation_id,
        "revision": record.revision,
        "payload": record.model_dump(mode="json"),
    }


async def _save(
    store: PostgresExtensionStore,
    kind: str,
    record: Any,
    expected: Any = None,
    scope: ExtensionScope = SCOPE,
) -> None:
    if kind == "skill":
        await store.save_skill(scope=scope, installation=record, expected_revision=expected)
    else:
        await store.save_mcp(scope=scope, connection=record, expected_revision=expected)


async def _get(
    store: PostgresExtensionStore,
    kind: str,
    scope: ExtensionScope = SCOPE,
    identifier: str = "config-a",
) -> Any:
    if kind == "skill":
        return await store.get_skill(scope=scope, installation_id=identifier)
    return await store.get_mcp(scope=scope, connection_id=identifier)


async def _list(
    store: PostgresExtensionStore,
    kind: str,
    scope: ExtensionScope = SCOPE,
    cursor: str | None = None,
) -> Any:
    page = ExtensionPageRequest(limit=2, cursor=cursor)
    if kind == "skill":
        return await store.list_skills(scope=scope, page=page)
    return await store.list_mcp(scope=scope, page=page)


def test_application_toggle_persists_with_cas(dsn: str, kind: str) -> None:
    store = PostgresExtensionStore(dsn, deployment_namespace="cloud-a")
    fresh = PostgresExtensionStore(dsn, deployment_namespace="cloud-a")

    async def check() -> None:
        original = _record(
            kind,
            **(
                {
                    "auth_mode": "bearer",
                    "auth_state": "ready",
                    "credential_ref": "credential://keep",
                }
                if kind == "mcp"
                else {}
            ),
        )
        await _save(store, kind, original)
        result = await set_extension_enabled(
            store=store,
            scope=SCOPE,
            kind=cast(Literal["skill", "mcp"], kind),
            object_id="config-a",
            expected_revision=1,
            enabled=False,
        )
        assert result.model_dump() == original.model_dump() | {"enabled": False, "revision": 2}
        assert await _get(fresh, kind) == result
        with pytest.raises(ExtensionRevisionConflictError):
            await set_extension_enabled(
                store=fresh,
                scope=SCOPE,
                kind=cast(Literal["skill", "mcp"], kind),
                object_id="config-a",
                expected_revision=1,
                enabled=True,
            )
        with pytest.raises(ExtensionNotFoundError):
            await set_extension_enabled(
                store=fresh,
                scope=SCOPE.model_copy(update={"principal_id": "other"}),
                kind=cast(Literal["skill", "mcp"], kind),
                object_id="config-a",
                expected_revision=2,
                enabled=True,
            )
        assert await _get(fresh, kind) == result

    asyncio.run(check())


def test_roundtrip_cas_and_history(dsn: str, kind: str) -> None:
    store = PostgresExtensionStore(dsn, deployment_namespace="cloud-a")

    async def check() -> None:
        original = _record(kind)
        with pytest.raises(ExtensionNotFoundError):
            await _get(store, kind)
        with pytest.raises(ExtensionNotFoundError):
            await _save(store, kind, _record(kind, revision=2), 1)
        await _save(store, kind, original)
        assert await _get(store, kind) == original
        with pytest.raises(ExtensionRevisionConflictError):
            await _save(store, kind, original)
        disabled = _record(kind, revision=2, enabled=False)
        results = await asyncio.gather(
            _save(store, kind, disabled, 1),
            _save(store, kind, disabled, 1),
            return_exceptions=True,
        )
        assert sum(result is None for result in results) == 1
        assert sum(isinstance(result, ExtensionRevisionConflictError) for result in results) == 1
        assert await _get(store, kind) == disabled
        assert (await _list(store, kind)).items == (disabled,)
        with store.connect() as connection:
            rows = connection.execute(
                "SELECT revision, payload FROM extension_configuration_revisions ORDER BY revision"
            ).fetchall()
        assert [row["revision"] for row in rows] == [1, 2]
        assert rows[0]["payload"] == original.model_dump(mode="json")
        assert rows[1]["payload"] == disabled.model_dump(mode="json")

    asyncio.run(check())


@pytest.mark.parametrize(
    "field",
    [
        "authority_issuer",
        "namespace_id",
        "principal_id",
        "workspace_id",
        "deployment",
    ],
)
def test_exact_scope_isolation(dsn: str, kind: str, field: str) -> None:
    store = PostgresExtensionStore(dsn, deployment_namespace="cloud-a")
    other_store = PostgresExtensionStore(
        dsn,
        deployment_namespace="cloud-b" if field == "deployment" else "cloud-a",
    )
    other_scope = SCOPE if field == "deployment" else SCOPE.model_copy(update={field: "other"})

    async def check() -> None:
        await _save(store, kind, _record(kind))
        with pytest.raises(ExtensionNotFoundError):
            await _get(other_store, kind, other_scope)
        assert not (await _list(other_store, kind, other_scope, "config-0")).items
        with pytest.raises(ExtensionNotFoundError):
            await _save(
                other_store, kind, _record(kind, scope=other_scope, revision=2), 1, other_scope
            )
        if field != "deployment":
            with pytest.raises(ValueError, match="scope"):
                await _save(store, kind, _record(kind, scope=other_scope))
        await _save(other_store, kind, _record(kind, scope=other_scope), scope=other_scope)
        assert (await _get(store, kind)).scope == SCOPE

    asyncio.run(check())


def test_bounded_keyset_pages(dsn: str, kind: str) -> None:
    store = PostgresExtensionStore(dsn, deployment_namespace="cloud-a")

    async def check() -> None:
        identifiers = ["a", "A", "b' OR 1=1 --", "z", "中"]
        for identifier in identifiers:
            await _save(
                store,
                kind,
                _record(kind, identifier, **({"enabled": False} if kind == "skill" else {})),
            )
        received: list[str] = []
        cursor = None
        while True:
            page = await _list(store, kind, cursor=cursor)
            assert len(page.items) <= 2
            received.extend(
                item.installation_id if kind == "skill" else item.connection_id
                for item in page.items
            )
            if page.next_cursor is None:
                break
            assert page.next_cursor != cursor
            cursor = page.next_cursor
        assert received == sorted(identifiers)

    asyncio.run(check())


def test_one_enabled_installation_per_skill_is_race_safe(dsn: str) -> None:
    store = PostgresExtensionStore(dsn, deployment_namespace="cloud-a")

    async def check() -> None:
        first = _record("skill", "install-a")
        second = _record("skill", "install-b")
        results = await asyncio.gather(
            _save(store, "skill", first),
            _save(store, "skill", second),
            return_exceptions=True,
        )
        assert sum(result is None for result in results) == 1
        assert sum(isinstance(result, ExtensionSkillConflictError) for result in results) == 1
        page = await store.list_skills(scope=SCOPE, page=ExtensionPageRequest(limit=10))
        assert len(page.items) == 1 and page.items[0].enabled

    asyncio.run(check())


def test_skill_advisory_lock_isolated_by_complete_scope(dsn: str) -> None:
    parameters = conninfo_to_dict(dsn)
    parameters["options"] = f"{parameters.get('options', '')} -c lock_timeout=250ms".strip()
    bounded = make_conninfo(**parameters)
    store = PostgresExtensionStore(bounded, deployment_namespace="cloud-a")
    other_scope = SCOPE.model_copy(update={"principal_id": "user-b"})
    lock_key = _skill_lock_key("cloud-a", SCOPE, "skill")

    with psycopg.connect(dsn) as blocker:
        blocker.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 52))",
            (lock_key,),
        )
        with pytest.raises(psycopg.errors.LockNotAvailable):
            asyncio.run(_save(store, "skill", _record("skill", "same-scope")))
        asyncio.run(
            _save(
                store,
                "skill",
                _record("skill", "other-scope", scope=other_scope),
                scope=other_scope,
            )
        )

    asyncio.run(_save(store, "skill", _record("skill", "same-scope")))


def test_disabled_skill_history_survives_enable_conflict(dsn: str) -> None:
    store = PostgresExtensionStore(dsn, deployment_namespace="cloud-a")

    async def check() -> None:
        first = _record("skill", "install-a", enabled=False)
        second = _record("skill", "install-b", enabled=False)
        await _save(store, "skill", first)
        await _save(store, "skill", second)
        await _save(store, "skill", first.model_copy(update={"enabled": True, "revision": 2}), 1)
        with pytest.raises(ExtensionSkillConflictError):
            await _save(
                store,
                "skill",
                second.model_copy(update={"enabled": True, "revision": 2}),
                1,
            )
        assert (await store.get_skill(scope=SCOPE, installation_id="install-b")) == second
        with store.connect() as connection:
            rows = connection.execute(
                "SELECT object_id, revision FROM extension_configuration_revisions "
                "ORDER BY object_id, revision"
            ).fetchall()
        assert [(row["object_id"], row["revision"]) for row in rows] == [
            ("install-a", 1),
            ("install-a", 2),
            ("install-b", 1),
        ]

    asyncio.run(check())


def test_snapshot_validation_uses_one_bounded_parameterized_query() -> None:
    installations = (_skill("install-a", "skill-a"), _skill("install-b", "skill-b"))
    connection = MagicMock()
    connection.execute.return_value.fetchall.return_value = [
        _snapshot_row(record) for record in installations
    ]

    validate_skill_snapshot_in_transaction(connection, "cloud-a", SCOPE, installations)

    connection.execute.assert_called_once()
    query, parameters = connection.execute.call_args.args
    assert "object_id = ANY(%s)" in query
    assert parameters[-1] == ["install-a", "install-b"]


def test_live_authorization_uses_one_query_for_32_skills() -> None:
    backends = tuple(Backend(name=f"skill-{index}") for index in range(32))
    installations = tuple(backend.installation for backend in backends)
    by_id = {backend.installation.installation_id: backend for backend in backends}
    rows = [
        {
            "ordinal": ordinal,
            "installation_id": item.installation_id,
            "object_id": item.installation_id,
            "revision": item.revision,
            "installation_payload": item.model_dump(mode="json"),
            "publication_payload": by_id[item.installation_id].publication.model_dump(mode="json"),
        }
        for ordinal, item in enumerate(installations)
    ]
    connection = MagicMock()
    connection.execute.return_value.fetchall.return_value = rows
    connection.__enter__.return_value = connection
    store = PostgresExtensionStore("host=unused", deployment_namespace="test")
    store.connect = MagicMock(return_value=connection)  # type: ignore[method-assign]

    authorized = store._authorize_frozen_skills(CLOUD_SCOPE, installations)

    assert len(authorized) == 32
    connection.execute.assert_called_once()
    query, parameters = connection.execute.call_args.args
    assert "jsonb_to_recordset" in query
    assert len(parameters[0].obj) == 32


@pytest.mark.parametrize("drift", ["missing", "revision", "disabled"])
def test_snapshot_validation_rejects_batched_configuration_drift(drift: str) -> None:
    installations = (_skill("install-a", "skill-a"), _skill("install-b", "skill-b"))
    rows = [_snapshot_row(record) for record in installations]
    if drift == "missing":
        rows.pop()
    elif drift == "revision":
        changed = installations[1].model_copy(update={"revision": 2})
        rows[1] = _snapshot_row(changed)
    else:
        changed = installations[1].model_copy(update={"enabled": False})
        rows[1] = _snapshot_row(changed)
    connection = MagicMock()
    connection.execute.return_value.fetchall.return_value = rows

    with pytest.raises(ExtensionSnapshotAdmissionConflictError):
        validate_skill_snapshot_in_transaction(connection, "cloud-a", SCOPE, installations)
    connection.execute.assert_called_once()


def test_snapshot_validation_rejects_more_than_32_without_querying() -> None:
    installations = tuple(_skill(f"install-{index}", f"skill-{index}") for index in range(33))
    connection = MagicMock()

    with pytest.raises(ExtensionSnapshotAdmissionConflictError, match="bound"):
        validate_skill_snapshot_in_transaction(connection, "cloud-a", SCOPE, installations)
    connection.execute.assert_not_called()


def test_maximum_unicode_coordinates(dsn: str, kind: str) -> None:
    opaque = "".join(chr(0x10000 + offset) for offset in range(512))
    scope = ExtensionScope(
        authority_issuer=opaque, namespace_id=opaque[:255], principal_id=opaque, workspace_id=opaque
    )
    store = PostgresExtensionStore(dsn, deployment_namespace=opaque[:255])

    async def check() -> None:
        record = _record(kind, opaque, scope=scope)
        await _save(store, kind, record, scope=scope)
        assert await _get(store, kind, scope, opaque) == record
        assert (await _list(store, kind, scope)).items == (record,)

    asyncio.run(check())


def test_concurrent_create_and_failed_history_roll_back(dsn: str, kind: str) -> None:
    store = PostgresExtensionStore(dsn, deployment_namespace="cloud-a")

    async def check() -> None:
        record = _record(kind)
        results = await asyncio.gather(
            _save(store, kind, record), _save(store, kind, record), return_exceptions=True
        )
        assert sum(result is None for result in results) == 1
        assert sum(isinstance(result, ExtensionRevisionConflictError) for result in results) == 1
        with store.connect() as connection:
            connection.execute(
                "ALTER TABLE extension_configuration_revisions "
                "ADD CONSTRAINT test_reject_update CHECK (revision = 1)"
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            await _save(store, kind, _record(kind, revision=2), 1)
        assert await _get(store, kind) == record
        with store.connect() as connection:
            assert connection.execute(
                "SELECT count(*) AS count FROM extension_configuration_revisions"
            ).fetchone() == {"count": 1}

    asyncio.run(check())


@pytest.mark.parametrize(
    "expected,revision", [(True, 2), (0, 1), (-1, 1), (1.0, 2), (None, 2), (1, 3)]
)
def test_invalid_revisions_need_no_connection(kind: str, expected: Any, revision: int) -> None:
    store = PostgresExtensionStore("host=invalid", deployment_namespace="cloud-a")
    with pytest.raises(ValueError):
        asyncio.run(_save(store, kind, _record(kind, revision=revision), expected))


@pytest.mark.parametrize("drift", ["scope", "id", "revision", "schema"])
def test_payload_drift_fails_closed(dsn: str, kind: str, drift: str) -> None:
    store = PostgresExtensionStore(dsn, deployment_namespace="cloud-a")
    original = _record(kind)
    asyncio.run(_save(store, kind, original))
    payload = original.model_dump(mode="json")
    if drift == "scope":
        payload["scope"]["principal_id"] = "other"
    elif drift == "id":
        payload["installation_id" if kind == "skill" else "connection_id"] = "other"
    elif drift == "revision":
        payload["revision"] = 7
    else:
        payload["raw_secret"] = "forbidden-test-value"
    with store.connect() as connection:
        connection.execute(
            "UPDATE extension_configuration_revisions SET payload = %s", (Jsonb(payload),)
        )
    with pytest.raises(ValueError):
        asyncio.run(_get(store, kind))
    with pytest.raises(ValueError):
        asyncio.run(_list(store, kind))
