from __future__ import annotations

from typing import Any

from agent_core.domain.user_personalization import (
    UserPersonalization,
    normalize_user_instructions,
)
from agent_core.ports.user_personalization import UserPersonalizationConflictError

from agent_storage.postgres.database import PostgresDatabase


class PostgresUserPersonalizationStore(PostgresDatabase):
    def get(self, user_id: str) -> UserPersonalization | None:
        user_id = _identity(user_id)
        with self.connect() as connection:
            row = connection.execute(
                """SELECT user_id, instructions, revision, updated_at, operator
                FROM user_personalization_settings
                WHERE deployment_namespace = %s AND user_id = %s""",
                (self.deployment_namespace, user_id),
            ).fetchone()
        return None if row is None else _record(row)

    def put(
        self,
        user_id: str,
        instructions: str,
        *,
        expected_revision: int,
        operator: str,
    ) -> UserPersonalization:
        return self._write(
            _identity(user_id),
            normalize_user_instructions(instructions),
            expected_revision=expected_revision,
            operator=_identity(operator),
        )

    def clear(
        self,
        user_id: str,
        *,
        expected_revision: int,
        operator: str,
    ) -> UserPersonalization:
        if expected_revision < 1:
            raise UserPersonalizationConflictError("personalization does not exist")
        return self._write(
            _identity(user_id),
            None,
            expected_revision=expected_revision,
            operator=_identity(operator),
        )

    def _write(
        self,
        user_id: str,
        instructions: str | None,
        *,
        expected_revision: int,
        operator: str,
    ) -> UserPersonalization:
        with self.connect() as connection:
            if expected_revision == 0:
                row = connection.execute(
                    """INSERT INTO user_personalization_settings (
                        deployment_namespace, user_id, instructions, revision, operator
                    ) VALUES (%s, %s, %s, 1, %s)
                    ON CONFLICT (deployment_namespace, user_id) DO NOTHING
                    RETURNING user_id, instructions, revision, updated_at, operator""",
                    (self.deployment_namespace, user_id, instructions, operator),
                ).fetchone()
            else:
                row = connection.execute(
                    """UPDATE user_personalization_settings
                    SET instructions = %s, revision = revision + 1, operator = %s,
                        updated_at = transaction_timestamp()
                    WHERE deployment_namespace = %s AND user_id = %s AND revision = %s
                    RETURNING user_id, instructions, revision, updated_at, operator""",
                    (
                        instructions,
                        operator,
                        self.deployment_namespace,
                        user_id,
                        expected_revision,
                    ),
                ).fetchone()
        if row is None:
            raise UserPersonalizationConflictError("personalization revision changed")
        return _record(row)


def _identity(value: str) -> str:
    if not value or value != value.strip() or len(value) > 255:
        raise ValueError("identity must be non-blank, trimmed, and at most 255 characters")
    return value


def _record(row: dict[str, Any]) -> UserPersonalization:
    return UserPersonalization(
        user_id=row["user_id"],
        instructions=row["instructions"],
        revision=row["revision"],
        updated_at=row["updated_at"],
        operator=row["operator"],
    )
