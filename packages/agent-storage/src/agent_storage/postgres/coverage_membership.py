"""Exact ordered membership seal; never a replacement for final original proof."""

import json
from hashlib import sha256
from typing import Any

from agent_core.domain.coverage_contracts import coverage_digest
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.coverage_snapshot import CoverageRecord
from agent_core.domain.coverage_validation import CoverageUnitKey, expected_units

from agent_storage.postgres.coverage_membership_migration import (
    COVERAGE_MEMBERSHIP_MIGRATION as MIGRATION,
)

FIELDS = ("record_id", "content_digest", "check_id", "check_version", "definition_digest",
          "kind", "part_id", "part_digest")


def key_chain(previous: str, key: CoverageUnitKey) -> str:
    # Fixed string/null array matches PostgreSQL jsonb_build_array::text exactly;
    # spaces inside strings are preserved, never stripped as JSON whitespace.
    body = json.dumps([getattr(key, field) for field in FIELDS], ensure_ascii=False)
    return sha256((previous + body).encode()).hexdigest()


def record_chain(previous: str, record: CoverageRecord) -> str:
    body = json.dumps([
        record.ordinal, record.record_id, record.content_digest,
        [[part.id, part.kind, part.digest, part.byte_length] for part in record.parts],
    ], ensure_ascii=False)
    return sha256((previous + body).encode()).hexdigest()


def membership_descriptor(
    binding: CoverageRunBinding, records: tuple[CoverageRecord, ...],
) -> dict[str, Any]:
    records = tuple(sorted(records, key=lambda row: row.ordinal))
    keys = expected_units(binding.contract, records)
    chain = sha256(b"coverage-membership/1").hexdigest()
    for key in keys:
        chain = key_chain(chain, key)
    records_chain = sha256(b"coverage-membership-records/1").hexdigest()
    for record in records:
        records_chain = record_chain(records_chain, record)
    return {
        "schema": "coverage-membership/1", "chain": chain,
        "expected_digest": coverage_digest([key.model_dump(mode="json") for key in keys]),
        "expected_count": len(keys),
        "records_chain": records_chain, "record_count": len(records),
    }


def membership_state(connection: Any, deployment: str, binding: CoverageRunBinding) -> Any:
    row = connection.execute(
        """SELECT s.* FROM coverage_membership_seals s JOIN coverage_runs r USING
           (deployment_namespace,namespace,run_id)
           WHERE s.deployment_namespace=%s AND s.namespace=%s AND s.run_id=%s
             AND s.sealed AND NOT s.invalidated AND NOT r.cancelled
             AND s.binding=r.binding AND EXISTS(SELECT 1 FROM zebra_schema_migrations
               WHERE version=%s AND name=%s AND checksum=%s)""",
        (deployment, binding.namespace, binding.run_id,
         MIGRATION.version, MIGRATION.name, MIGRATION.checksum),
    ).fetchone()
    if row is None:
        return None  # Legacy/rebuild/unsupported mutation retains independent proof.
    if (row["session_id"] != binding.session_id or row["binding"] != binding.model_dump(mode="json")
            or row["seeded"] != row["expected_count"] or row["chain"] != row["target_chain"]
            or row["record_count"] != binding.snapshot.record_count
            or row["records_seeded"] != row["record_count"]
            or row["records_chain"] != row["target_records_chain"]
            or not 0 <= row["remaining_parts"] <= row["part_count"] <= row["expected_count"]):
        raise ValueError("sealed exact coverage membership conflicts")
    return row


def membership_records(
    connection: Any, deployment: str, binding: CoverageRunBinding, record_ids: set[str],
) -> tuple[CoverageRecord, ...]:
    """Only called after the same locked transaction qualifies exact membership."""
    if len(record_ids) > 1000:
        raise ValueError("coverage membership delta exceeds bounded record page")
    rows = connection.execute(
        """SELECT record FROM coverage_membership_records WHERE deployment_namespace=%s
           AND namespace=%s AND run_id=%s AND record_id=ANY(%s) ORDER BY ordinal LIMIT 1001""",
        (deployment, binding.namespace, binding.run_id, sorted(record_ids)),
    ).fetchall()
    records = tuple(CoverageRecord.model_validate(row["record"]) for row in rows)
    if {row.record_id for row in records} != record_ids or len(records) != len(record_ids):
        raise ValueError("coverage membership selected records are missing or conflicting")
    return records
