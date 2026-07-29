"""Shared immutable PostgreSQL migration definitions."""

import hashlib
from dataclasses import dataclass


class PostgresMigrationError(RuntimeError):
    """Raised when the database migration history is not trusted."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        content = "\n-- statement --\n".join(self.statements).encode()
        return hashlib.sha256(content).hexdigest()
