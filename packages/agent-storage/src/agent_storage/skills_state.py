from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from agent_core.domain.skills import SkillComponentIdentity

from agent_storage.database import SQLiteDatabase

_MAX_PACKAGE_FILES = 128
_MAX_PACKAGE_BYTES = 262_144


@dataclass(frozen=True)
class SkillStateRecord:
    name: str
    scope: str
    enabled: bool
    updated_at: datetime
    operator: str | None
    namespace: str | None = None
    digest: str | None = None
    owner: str | None = None


@dataclass(frozen=True)
class InstalledSkillRecord:
    identity: SkillComponentIdentity
    owner: str
    files: Mapping[str, str]
    installed_at: datetime
    operator: str | None


class SQLiteSkillsStateStore:
    """Legacy enablement plus immutable private-Skill installation records.

    The legacy ``(name, scope)`` rows remain backward compatible; private records
    pin an owner-scoped exact identity and declarative package snapshot.
    """

    def __init__(self, database_path: str | Path) -> None:
        self._database = SQLiteDatabase(database_path)
        self._initialize()

    def set_enabled(
        self,
        *,
        name: str,
        scope: str,
        enabled: bool,
        operator: str | None,
        updated_at: datetime | None = None,
    ) -> SkillStateRecord:
        record = SkillStateRecord(
            name=name,
            scope=scope,
            enabled=enabled,
            updated_at=updated_at or datetime.now(UTC),
            operator=operator,
        )
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO skills_state (name, scope, enabled, updated_at, operator)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name, scope) DO UPDATE SET
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at,
                    operator = excluded.operator
                """,
                (
                    record.name,
                    record.scope,
                    1 if record.enabled else 0,
                    record.updated_at.isoformat(),
                    record.operator,
                ),
            )
        return record

    def install_component(
        self,
        *,
        identity: SkillComponentIdentity,
        files: Mapping[str, str],
        owner: str,
        operator: str | None,
        installed_at: datetime | None = None,
    ) -> InstalledSkillRecord:
        _validate_private_identity(identity, owner)
        normalized_files = _normalize_files(files)
        if _component_digest(normalized_files["SKILL.md"]) != identity.digest:
            raise ValueError("installed Skill content does not match its identity digest")
        record = InstalledSkillRecord(
            identity=identity,
            owner=owner,
            files=normalized_files,
            installed_at=installed_at or datetime.now(UTC),
            operator=operator,
        )
        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT * FROM skill_installations
                WHERE owner = ? AND name = ? AND scope = ? AND namespace = ? AND version = ?
                """,
                (owner, identity.name, identity.scope, identity.namespace, identity.version),
            ).fetchone()
            if existing is not None:
                existing_record = _row_to_installation(existing)
                if (
                    existing_record.identity.digest != identity.digest
                    or existing_record.identity.source != identity.source
                    or dict(existing_record.files) != dict(normalized_files)
                ):
                    raise ValueError("installed Skill version is immutable")
                return existing_record
            connection.execute(
                """
                INSERT INTO skill_installations (
                    owner, name, version, digest, scope, namespace, source,
                    files_json, installed_at, operator
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    owner,
                    identity.name,
                    identity.version,
                    identity.digest,
                    identity.scope,
                    identity.namespace,
                    identity.source,
                    json.dumps(dict(normalized_files), sort_keys=True),
                    record.installed_at.isoformat(),
                    operator,
                ),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO skill_component_state (
                    owner, name, version, scope, namespace, digest, enabled, updated_at, operator
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    owner,
                    identity.name,
                    identity.version,
                    identity.scope,
                    identity.namespace,
                    identity.digest,
                    record.installed_at.isoformat(),
                    operator,
                ),
            )
        return record

    def installed_component(
        self,
        *,
        identity: SkillComponentIdentity,
        owner: str,
    ) -> InstalledSkillRecord | None:
        _validate_private_identity(identity, owner)
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM skill_installations
                WHERE owner = ? AND name = ? AND version = ? AND digest = ?
                  AND scope = ? AND namespace = ? AND source = ?
                """,
                (
                    owner,
                    identity.name,
                    identity.version,
                    identity.digest,
                    identity.scope,
                    identity.namespace,
                    identity.source,
                ),
            ).fetchone()
        return None if row is None else _row_to_installation(row)

    def installed_component_identities(
        self, *, owner: str, enabled: bool | None = None
    ) -> tuple[SkillComponentIdentity, ...]:
        enabled_value = None if enabled is None else int(enabled)
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT i.name, i.version, i.digest, i.scope, i.namespace, i.source
                FROM skill_installations AS i
                JOIN skill_component_state AS s
                  ON s.owner = i.owner AND s.name = i.name AND s.version = i.version
                 AND s.scope = i.scope AND s.namespace = i.namespace AND s.digest = i.digest
                WHERE i.owner = ? AND (? IS NULL OR s.enabled = ?)
                ORDER BY i.name, i.version, i.digest
                """,
                (owner, enabled_value, enabled_value),
            ).fetchall()
        return tuple(_identity_from_row(row) for row in rows)

    def set_component_enabled(
        self,
        *,
        identity: SkillComponentIdentity,
        owner: str,
        enabled: bool,
        operator: str | None,
        updated_at: datetime | None = None,
    ) -> SkillStateRecord:
        if self.installed_component(identity=identity, owner=owner) is None:
            raise ValueError("private Skill must be installed before it can be enabled")
        record = SkillStateRecord(
            name=identity.name,
            scope=identity.scope,
            enabled=enabled,
            updated_at=updated_at or datetime.now(UTC),
            operator=operator,
            namespace=identity.namespace,
            digest=identity.digest,
            owner=owner,
        )
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO skill_component_state (
                    owner, name, version, scope, namespace, digest, enabled, updated_at, operator
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner, name, scope, namespace, version, digest) DO UPDATE SET
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at,
                    operator = excluded.operator
                """,
                (
                    owner,
                    identity.name,
                    identity.version,
                    identity.scope,
                    identity.namespace,
                    identity.digest,
                    1 if enabled else 0,
                    record.updated_at.isoformat(),
                    operator,
                ),
            )
        return record

    def component_state(
        self, *, identity: SkillComponentIdentity, owner: str
    ) -> SkillStateRecord | None:
        _validate_private_identity(identity, owner)
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM skill_component_state
                WHERE owner = ? AND name = ? AND version = ? AND scope = ?
                  AND namespace = ? AND digest = ?
                """,
                (
                    owner,
                    identity.name,
                    identity.version,
                    identity.scope,
                    identity.namespace,
                    identity.digest,
                ),
            ).fetchone()
        return None if row is None else _row_to_component_state(row)

    def is_component_enabled(self, *, identity: SkillComponentIdentity, owner: str) -> bool:
        state = self.component_state(identity=identity, owner=owner)
        return state is not None and state.enabled

    def get_state(self, *, name: str, scope: str) -> SkillStateRecord | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT name, scope, enabled, updated_at, operator
                FROM skills_state WHERE name = ? AND scope = ?
                """,
                (name, scope),
            ).fetchone()
        return None if row is None else _row_to_record(row)

    def list_states(self) -> tuple[SkillStateRecord, ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT name, scope, enabled, updated_at, operator
                FROM skills_state ORDER BY name, scope
                """
            ).fetchall()
        return tuple(_row_to_record(row) for row in rows)

    def disabled_components(self) -> frozenset[tuple[str, str]]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT name, scope FROM skills_state WHERE enabled = 0"
            ).fetchall()
        return frozenset((row["name"], row["scope"]) for row in rows)

    def _initialize(self) -> None:
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS skills_state (
                    name TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    operator TEXT,
                    PRIMARY KEY (name, scope)
                );
                CREATE TABLE IF NOT EXISTS skill_installations (
                    owner TEXT NOT NULL,
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    source TEXT NOT NULL,
                    files_json TEXT NOT NULL,
                    installed_at TEXT NOT NULL,
                    operator TEXT,
                    PRIMARY KEY (owner, name, scope, namespace, version)
                );
                CREATE TABLE IF NOT EXISTS skill_component_state (
                    owner TEXT NOT NULL,
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    operator TEXT,
                    PRIMARY KEY (owner, name, scope, namespace, version, digest)
                );
                """
            )


def _validate_private_identity(identity: SkillComponentIdentity, owner: str) -> None:
    if (
        identity.scope != "user"
        or identity.namespace != owner
        or identity.version is None
        or not owner
        or owner == "user"
        or "/" in owner
    ):
        raise ValueError("private Skill identity must have an owner-scoped immutable version")


def _normalize_files(files: Mapping[str, str]) -> Mapping[str, str]:
    if not isinstance(files, Mapping) or "SKILL.md" not in files or len(files) > _MAX_PACKAGE_FILES:
        raise ValueError("installed Skill package is invalid")
    normalized: dict[str, str] = {}
    total = 0
    for path, content in files.items():
        pure = PurePosixPath(path)
        if (
            not isinstance(path, str)
            or not isinstance(content, str)
            or pure.is_absolute()
            or ".." in pure.parts
            or path != pure.as_posix()
        ):
            raise ValueError("installed Skill package is invalid")
        byte_count = len(content.encode("utf-8"))
        if byte_count > 32_768:
            raise ValueError("installed Skill package is invalid")
        total += byte_count
        normalized[path] = content
    if total > _MAX_PACKAGE_BYTES:
        raise ValueError("installed Skill package exceeds its bound")
    return MappingProxyType(dict(sorted(normalized.items())))


def _component_digest(content: str) -> str:
    raw = content.encode("utf-8")
    if not raw.startswith(b"---\n"):
        raise ValueError("installed Skill package is invalid")
    end = raw.find(b"\n---", 4)
    if end < 0:
        raise ValueError("installed Skill package is invalid")
    digest = sha256()
    digest.update(b"skill-manifest-v1\n")
    digest.update(raw[: end + 4])
    digest.update(b"\nskill-body-v1\n")
    digest.update(raw[end + 4 :])
    return digest.hexdigest()


def _row_to_record(row: Any) -> SkillStateRecord:
    return SkillStateRecord(
        name=row["name"],
        scope=row["scope"],
        enabled=bool(row["enabled"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        operator=row["operator"],
    )


def _row_to_component_state(row: Any) -> SkillStateRecord:
    return SkillStateRecord(
        name=row["name"],
        scope=row["scope"],
        enabled=bool(row["enabled"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        operator=row["operator"],
        namespace=row["namespace"],
        digest=row["digest"],
        owner=row["owner"],
    )


def _row_to_installation(row: Any) -> InstalledSkillRecord:
    parsed = json.loads(row["files_json"])
    files = _normalize_files(parsed)
    return InstalledSkillRecord(
        identity=_identity_from_row(row),
        owner=row["owner"],
        files=files,
        installed_at=datetime.fromisoformat(row["installed_at"]),
        operator=row["operator"],
    )


def _identity_from_row(row: Any) -> SkillComponentIdentity:
    return SkillComponentIdentity(
        name=row["name"],
        version=row["version"],
        digest=row["digest"],
        scope=row["scope"],
        namespace=row["namespace"],
        source=row["source"],
    )
