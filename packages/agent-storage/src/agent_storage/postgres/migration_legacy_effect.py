"""Manifest-bound quarantine for legacy SQLite Effect/Delivery metadata."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from agent_storage.postgres.migration_snapshot import SnapshotRecord, SQLiteSnapshot

_SCHEMA = "zebra.sqlite.legacy.effect_delivery.quarantine.v1"
_SOURCE_TABLE = "effect_ledger"
_REASON = "missing_cloud_authority_bindings"
_DISPOSITION = "quarantine_rebuild_required"
_UNAVAILABLE_FIELDS = (
    "deployment_namespace",
    "dispatch_id",
    "execution_session_id",
    "retry_key",
    "request_hash",
    "payload_artifact_ref",
    "claim_epoch",
    "claim_fencing_token",
    "claim_owner_instance_id",
    "claim_expires_at",
    "intent_event_id",
    "terminal_event_id",
    "evidence",
    "evidence_history",
)


class EffectQuarantineError(ValueError):
    """Raised when a legacy Effect/Delivery quarantine artifact is invalid."""


@dataclass(frozen=True, slots=True)
class EffectQuarantineManifest:
    source_snapshot_manifest_sha256: str
    record_count: int
    records_sha256: str
    unavailable_fields: tuple[str, ...] = _UNAVAILABLE_FIELDS
    schema: str = _SCHEMA
    source_table: str = _SOURCE_TABLE
    reason: str = _REASON
    disposition: str = _DISPOSITION

    @property
    def digest(self) -> str:
        return _sha256_json(self.as_dict(include_digest=False))

    def as_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "disposition": self.disposition,
            "reason": self.reason,
            "record_count": self.record_count,
            "records_sha256": self.records_sha256,
            "schema": self.schema,
            "source_snapshot_manifest_sha256": self.source_snapshot_manifest_sha256,
            "source_table": self.source_table,
            "unavailable_fields": self.unavailable_fields,
        }
        if include_digest:
            value["manifest_sha256"] = self.digest
        return value


@dataclass(frozen=True, slots=True)
class EffectQuarantine:
    records: tuple[SnapshotRecord, ...]
    manifest: EffectQuarantineManifest


def build_effect_quarantine(snapshot: SQLiteSnapshot) -> EffectQuarantine:
    """Build a deterministic quarantine artifact without touching PostgreSQL."""
    table_names = {table for table, _ in snapshot.manifest.table_counts}
    if _SOURCE_TABLE not in table_names:
        raise EffectQuarantineError("snapshot does not contain effect_ledger")
    records = tuple(
        sorted(
            (record for record in snapshot.records if record.table == _SOURCE_TABLE),
            key=lambda record: record.as_json(),
        )
    )
    if any(len(record.columns) != len(record.values) for record in records):
        raise EffectQuarantineError("Effect quarantine row is malformed")
    manifest = EffectQuarantineManifest(
        source_snapshot_manifest_sha256=snapshot.manifest.digest,
        record_count=len(records),
        records_sha256=_records_sha256(records),
    )
    return EffectQuarantine(records=records, manifest=manifest)


def write_effect_quarantine(
    quarantine: EffectQuarantine, directory: str | Path
) -> EffectQuarantineManifest:
    """Write canonical quarantine records and manifest to a new directory."""
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(record.as_json() for record in quarantine.records)
    (output / "records.jsonl").write_text(f"{lines}\n" if lines else "", encoding="utf-8")
    (output / "manifest.json").write_text(
        f"{_canonical_json(quarantine.manifest.as_dict())}\n", encoding="utf-8"
    )
    return quarantine.manifest


def load_effect_quarantine(directory: str | Path) -> EffectQuarantine:
    """Load and verify a quarantine artifact before any rebuild decision."""
    root = Path(directory)
    try:
        manifest_data = json.loads(
            (root / "manifest.json").read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
        )
        lines = (root / "records.jsonl").read_text(encoding="utf-8").splitlines()
    except (OSError, json.JSONDecodeError) as error:
        raise EffectQuarantineError("Effect quarantine files are unreadable") from error
    records = tuple(_record_from_json(line) for line in lines if line)
    manifest = _manifest_from_json(manifest_data)
    if manifest.record_count != len(records):
        raise EffectQuarantineError("Effect quarantine record count mismatch")
    if records != tuple(sorted(records, key=lambda record: record.as_json())):
        raise EffectQuarantineError("Effect quarantine records are not canonical")
    if any(record.table != _SOURCE_TABLE for record in records):
        raise EffectQuarantineError("Effect quarantine source table changed")
    if manifest.records_sha256 != _records_sha256(records):
        raise EffectQuarantineError("Effect quarantine records checksum mismatch")
    if manifest_data.get("manifest_sha256") != manifest.digest:
        raise EffectQuarantineError("Effect quarantine manifest checksum mismatch")
    return EffectQuarantine(records=records, manifest=manifest)


def _manifest_from_json(value: object) -> EffectQuarantineManifest:
    if not isinstance(value, dict):
        raise EffectQuarantineError("Effect quarantine manifest is malformed")
    try:
        unavailable = tuple(str(item) for item in value["unavailable_fields"])
        manifest = EffectQuarantineManifest(
            source_snapshot_manifest_sha256=str(value["source_snapshot_manifest_sha256"]),
            record_count=int(value["record_count"]),
            records_sha256=str(value["records_sha256"]),
            unavailable_fields=unavailable,
            schema=str(value["schema"]),
            source_table=str(value["source_table"]),
            reason=str(value["reason"]),
            disposition=str(value["disposition"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise EffectQuarantineError("Effect quarantine manifest is malformed") from error
    if (
        manifest.schema != _SCHEMA
        or manifest.source_table != _SOURCE_TABLE
        or manifest.reason != _REASON
        or manifest.disposition != _DISPOSITION
        or manifest.unavailable_fields != _UNAVAILABLE_FIELDS
        or manifest.record_count < 0
    ):
        raise EffectQuarantineError("Effect quarantine manifest contract changed")
    _require_digest(manifest.source_snapshot_manifest_sha256, "source snapshot")
    _require_digest(manifest.records_sha256, "records")
    return manifest


def _record_from_json(line: str) -> SnapshotRecord:
    try:
        value = json.loads(line, parse_constant=_reject_json_constant)
        record = SnapshotRecord(
            table=str(value["table"]),
            columns=tuple(str(item) for item in value["columns"]),
            values=tuple(value["values"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise EffectQuarantineError("Effect quarantine row is malformed") from error
    if len(record.columns) != len(record.values):
        raise EffectQuarantineError("Effect quarantine row column mismatch")
    return record


def _records_sha256(records: Sequence[SnapshotRecord]) -> str:
    return hashlib.sha256(
        "\n".join(record.as_json() for record in records).encode("utf-8")
    ).hexdigest()


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _reject_json_constant(value: str) -> object:
    raise EffectQuarantineError(f"non-finite JSON value is not allowed: {value}")


def _require_digest(value: str, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise EffectQuarantineError(f"{label} checksum is invalid")
