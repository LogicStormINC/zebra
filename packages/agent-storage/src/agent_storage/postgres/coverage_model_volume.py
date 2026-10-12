"""Global MODEL proof bounds with explicitly scoped incremental lifecycle checks."""

from datetime import datetime
from types import EllipsisType
from typing import Any

from agent_core.domain.coverage_model_budget import CoverageModelPolicy, CoverageModelUsageReceipt
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.coverage_validation import CoverageUnitKey
from psycopg.types.json import Jsonb

from agent_storage.postgres.coverage_model_volume_summary import volume_summary
from agent_storage.postgres.coverage_proof_prefetch import prefetch_proof


def preflight_original_volume(
    connection: Any,
    deployment: str,
    binding: CoverageRunBinding,
    *,
    candidate: CoverageModelUsageReceipt | None = None,
    reserved_sequence: int | None = None,
    retention_deadlines: list[datetime] | None = None,
    _incremental_keys: set[CoverageUnitKey] | None = None,
    _policy: CoverageModelPolicy | None | EllipsisType = ...,
    _artifacts: Any = None,
) -> None:
    """lock_run fences writes; retries count once; originals precede object I/O."""
    from agent_storage.postgres import coverage_model_source as source

    if _incremental_keys is not None:
        policy = source.task_policy(connection, deployment, binding) if _policy is ... else _policy
        if policy is None or policy.validation_mode != "final_certification":
            raise ValueError("incremental preflight requires final_certification admission")
    deadlines = [] if retention_deadlines is None else retention_deadlines
    root = (volume_summary(connection, deployment, binding)
            if _incremental_keys is not None else None)
    volume = ({"count": root["initialized"] + root["reserved"] + root["receipts"],
               "bytes": root["source_bytes"]} if root is not None else connection.execute(
        """SELECT count(*) AS count,coalesce(sum(octet_length(to_jsonb(e)::text)),0) AS bytes
           FROM session_events e WHERE deployment_namespace=%s AND session_id=%s
           AND payload->>'namespace'=%s AND payload->>'run_id'=%s AND event_type=ANY(%s)""",
        (deployment, binding.session_id, binding.namespace, binding.run_id,
         list(source.MODEL_TYPES)),
    ).fetchone())
    if volume["count"] > 400001 or volume["bytes"] > source.MAX_COVERAGE_ARTIFACT_BYTES:
        raise ValueError("model source proof exceeds bounded replay volume")
    source_sql = """SELECT e.payload->'receipt' AS receipt,e.sequence,
           r.sequence AS reserved_sequence,
           r.payload->'reservation' AS reservation,m.size_bytes FROM session_events e
           LEFT JOIN artifact_payload_metadata m ON m.deployment_namespace=e.deployment_namespace
             AND m.artifact_id=CASE WHEN e.payload->'receipt'->>'checkpoint_ref'
               ~ '^artifact://[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
               THEN substring(e.payload->'receipt'->>'checkpoint_ref' FROM 12)::uuid END
           LEFT JOIN session_events r ON r.deployment_namespace=e.deployment_namespace
             AND r.session_id=e.session_id AND r.payload->>'namespace'=e.payload->>'namespace'
             AND r.payload->>'run_id'=e.payload->>'run_id'
             AND r.event_type='coverage_model_call_reserved'
             AND r.payload->'reservation'->>'reservation_key'
               =e.payload->'receipt'->'reservation'->>'reservation_key'
           WHERE e.deployment_namespace=%s AND e.session_id=%s
             AND e.payload->>'namespace'=%s AND e.payload->>'run_id'=%s
             AND e.event_type='coverage_model_usage_recorded'"""
    source_params: tuple[Any, ...] = (
        deployment, binding.session_id, binding.namespace, binding.run_id
    )
    sizes = ({"count": root["original_count"], "unique_count": root["original_count"],
              "available": root["original_count"], "bytes": root["original_bytes"],
              "last": root["volume_watermark"]} if root is not None else connection.execute(
        "SELECT count(*) AS count,count(DISTINCT sequence) AS unique_count,"
        "max(sequence) AS last,count(size_bytes) AS available,"
        "coalesce(sum(size_bytes),0) AS bytes FROM (" + source_sql + ") originals",
        source_params,
    ).fetchone())
    if sizes["count"] != sizes["unique_count"]:
        raise ValueError("strict MODEL original source is duplicate or conflicting")
    if (
        sizes["count"] > 200000
        or sizes["available"] != sizes["count"]
        or sizes["bytes"] > source.MAX_COVERAGE_ARTIFACT_BYTES
    ):
        raise ValueError("strict MODEL original proof exceeds cumulative read bound")
    upper = sizes["last"]
    if _incremental_keys is not None:
        # Global bounds come from the native root, or legacy aggregates. Only
        # delta lifecycle proofs are enumerated; final/recovery retain full scans.
        source_sql += """ AND (e.payload->'receipt'->'reservation'->'key'=ANY(%s::jsonb[])
            OR e.payload->'receipt'->'reservation'->>'reservation_key'=%s)"""
        source_params += (
            [Jsonb(key.model_dump(mode="json")) for key in _incremental_keys],
            None if candidate is None else candidate.reservation.reservation_key,
        )
        if not _incremental_keys and candidate is None:
            upper = None
    settled: set[str] = set()
    previous = None
    total = sizes["bytes"]
    for row in source.original_rows(
        connection, source_sql, source_params, upper, artifacts=_artifacts,
    ):
        receipt = CoverageModelUsageReceipt.model_validate(row["receipt"])
        key = receipt.reservation.reservation_key
        if (
            key in settled
            or type(row["reserved_sequence"]) is not int
            or row["reserved_sequence"] <= 0
            or row["reservation"] != receipt.reservation.model_dump(mode="json")
        ):
            raise ValueError("strict MODEL original source is duplicate or conflicting")
        record = source.checkpoint_source(
            connection,
            deployment,
            binding,
            receipt,
            reserved_sequence=row["reserved_sequence"],
            receipt_sequence=row["sequence"],
            artifacts=_artifacts,
        )
        if record.reservation.size_bytes != row["size_bytes"]:
            raise ValueError("strict MODEL original metadata changed during preflight")
        if record.reservation.retained_until is not None:
            deadlines[:] = [
                min(deadlines[0], record.reservation.retained_until)
                if deadlines
                else record.reservation.retained_until
            ]
        settled.add(key)
        if candidate is not None and key == candidate.reservation.reservation_key:
            previous = receipt
    if candidate is not None:
        if previous is not None:
            if previous != candidate:
                raise ValueError("strict MODEL original retry conflicts with source")
        else:
            if type(reserved_sequence) is not int:
                raise ValueError("strict MODEL candidate requires its reserved source sequence")
            if candidate.checkpoint_ref is not None:
                prefetch_proof(_artifacts, (candidate.checkpoint_ref,))
            record = source.checkpoint_source(
                connection, deployment, binding, candidate,
                reserved_sequence=reserved_sequence, artifacts=_artifacts,
            )
            total += record.reservation.size_bytes
            if record.reservation.retained_until is not None:
                deadlines[:] = [
                    min(deadlines[0], record.reservation.retained_until)
                    if deadlines
                    else record.reservation.retained_until
                ]
    if total > source.MAX_COVERAGE_ARTIFACT_BYTES:
        raise ValueError("strict MODEL original proof exceeds cumulative read bound")
    source.check_checkpoint_retention(connection, deadlines)
