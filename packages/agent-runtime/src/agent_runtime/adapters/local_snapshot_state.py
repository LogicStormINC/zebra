from dataclasses import dataclass
from enum import StrEnum


class LocalSnapshotStatus(StrEnum):
    VALID = "valid"
    MISSING = "missing"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True)
class LocalSnapshotInspection:
    snapshot_id: str
    snapshot_path: str | None
    status: LocalSnapshotStatus
    problems: tuple[str, ...] = ()

    @property
    def restorable(self) -> bool:
        return self.status is LocalSnapshotStatus.VALID


@dataclass(frozen=True)
class LocalSnapshotCleanupResult:
    snapshot_id: str
    snapshot_path: str | None
    status: LocalSnapshotStatus
    removed: bool
    problems: tuple[str, ...] = ()
