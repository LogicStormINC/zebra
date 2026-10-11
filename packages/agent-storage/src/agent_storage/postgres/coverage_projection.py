"""Exact membership indexes; only validated source Events populate these tables."""

import json
from typing import Any

from agent_core.domain.coverage_contracts import coverage_digest
from agent_core.domain.coverage_persistence import CoverageRunBinding, coverage_result_bytes
from agent_core.domain.coverage_snapshot import CoverageRecord
from agent_core.domain.coverage_validation import expected_units
from agent_core.domain.events import EventType, SessionEvent
from agent_core.ports.artifact_payload_store import ArtifactPayloadStorePort
from agent_core.ports.coverage import CoverageCommit, CoverageCommitReceipt
from psycopg.types.json import Jsonb

from agent_storage.postgres.coverage_artifacts import read_artifact
from agent_storage.postgres.coverage_transactions import (
    request_digest,
    validate_event_fence,
    validate_request,
)


def seed_run(
    connection: Any,
    deployment: str,
    binding: CoverageRunBinding,
    records: tuple[CoverageRecord, ...],
    watermark: int,
) -> int:
    connection.execute(
        """INSERT INTO coverage_runs
           (deployment_namespace, namespace, run_id, session_id, task_id, binding, source_watermark)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (
            deployment,
            binding.namespace,
            binding.run_id,
            binding.session_id,
            binding.task_id,
            Jsonb(binding.model_dump(mode="json")),
            watermark,
        ),
    )
    ordinal = 0
    seal_records = any(check.kind == "model" for check in binding.contract.checks)
    # ponytail: stream one record's expected units at a time; upgrade to COPY only
    # if measured bind throughput requires it. Commits never regenerate this index.
    with connection.cursor() as cursor:
        for record in sorted(records, key=lambda row: row.ordinal):
            units = expected_units(binding.contract, (record,))
            cursor.executemany(
                """INSERT INTO coverage_units
                   (deployment_namespace,namespace,run_id,unit_digest,ordinal,unit_key,record)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (
                    (
                        deployment,
                        binding.namespace,
                        binding.run_id,
                        coverage_digest(unit.model_dump(mode="json")),
                        ordinal + offset,
                        Jsonb(unit.model_dump(mode="json")),
                        Jsonb(record.model_dump(mode="json")) if seal_records
                        and unit.kind == "record_merge"
                        and unit.check_id == binding.contract.checks[0].id else None,
                    )
                    for offset, unit in enumerate(units)
                ),
            )
            ordinal += len(units)
    project_watermark(connection, deployment, binding, watermark, cancelled=False)
    return ordinal


def accept_units(connection: Any, deployment: str, request: CoverageCommit) -> None:
    keys = [result.key.model_dump(mode="json") for result in request.results]
    if len({coverage_digest(key) for key in keys}) != len(keys):
        raise ValueError("coverage unit is repeated in the batch")
    updated = connection.execute(
        """UPDATE coverage_units u SET result=d.result
           FROM jsonb_to_recordset(%s) AS d(unit_digest text,unit_key jsonb,result jsonb)
           WHERE u.deployment_namespace=%s AND u.namespace=%s AND u.run_id=%s
             AND u.unit_digest=d.unit_digest AND u.unit_key=d.unit_key AND u.result IS NULL
           RETURNING u.ordinal""",
        (Jsonb([{"unit_digest": coverage_digest(key), "unit_key": key,
                 "result": result.model_dump(mode="json")}
                for key, result in zip(keys, request.results, strict=True)]),
         deployment, request.namespace, request.run_id),
    ).fetchall()
    if len(updated) != len(request.results):
        # The caller owns the transaction; a partial match must roll it all back.
        raise ValueError("coverage unit is unexpected, changed or already accepted")


def receipt_from_event(event: SessionEvent) -> CoverageCommitReceipt:
    validate_event_fence(event.payload)
    request = event.payload["request"]
    return CoverageCommitReceipt(
        namespace=event.payload["namespace"],
        run_id=event.payload["run_id"],
        commit_key=request["commit_key"],
        result_artifact_digest=request["result_artifact_digest"],
        event_watermark=event.sequence,
        committed_at=event.created_at,
    )


def project_batch(
    connection: Any,
    deployment: str,
    binding: CoverageRunBinding,
    request: CoverageCommit,
    event: SessionEvent,
) -> CoverageCommitReceipt:
    receipt = receipt_from_event(event)
    connection.execute(
        """INSERT INTO coverage_batches
           (deployment_namespace,namespace,run_id,commit_key,request_digest,receipt,event_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (
            deployment,
            request.namespace,
            request.run_id,
            request.commit_key,
            request_digest(request),
            Jsonb(receipt.model_dump(mode="json")),
            event.event_id,
        ),
    )
    project_watermark(connection, deployment, binding, event.sequence, cancelled=False)
    return receipt


def project_watermark(
    connection: Any,
    deployment: str,
    binding: CoverageRunBinding,
    watermark: int,
    *,
    cancelled: bool,
) -> None:
    params = (deployment, binding.namespace, binding.run_id)
    connection.execute(
        """UPDATE coverage_runs SET source_watermark=%s,cancelled=%s
           WHERE deployment_namespace=%s AND namespace=%s AND run_id=%s""",
        (watermark, cancelled, *params),
    )
    if cancelled:
        connection.execute(
            """DELETE FROM coverage_continuations WHERE deployment_namespace=%s
               AND namespace=%s AND run_id=%s""",
            params,
        )
    else:
        # Dormant durable intent only: no broker publication or executor admission.
        connection.execute(
            """INSERT INTO coverage_continuations
               (deployment_namespace,namespace,run_id,source_watermark) VALUES (%s,%s,%s,%s)
               ON CONFLICT (deployment_namespace,namespace,run_id)
               DO UPDATE SET source_watermark=EXCLUDED.source_watermark""",
            (*params, watermark),
        )


def replay_request(
    artifacts: ArtifactPayloadStorePort,
    binding: CoverageRunBinding,
    event: SessionEvent,
) -> CoverageCommit:
    validate_event_fence(event.payload)
    descriptor = event.payload["request"]
    body = read_artifact(
        artifacts,
        descriptor["result_artifact_ref"],
        descriptor["result_artifact_digest"],
        binding.session_id,
    )
    data = json.loads(body)
    if not isinstance(data, dict) or set(data) != {"schema", "results"}:
        raise ValueError("invalid coverage results Artifact schema")
    if data["schema"] != "coverage-results/1" or not isinstance(data["results"], list):
        raise ValueError("invalid coverage results Artifact schema")
    if "results" in descriptor:
        raise ValueError("coverage Event must not embed unbounded results")
    request = CoverageCommit.model_validate({**descriptor, "results": data["results"]})
    validate_request(binding, request)
    if body != coverage_result_bytes(request.results):
        raise ValueError("coverage result Artifact disagrees with the exact canonical batch")
    if (
        event.event_type != EventType.COVERAGE_BATCH_ACCEPTED
        or event.session_id != binding.session_id
        or event.payload["namespace"] != binding.namespace
        or event.payload["run_id"] != binding.run_id
        or event.payload["request_digest"] != request_digest(request)
        or event.payload["result_count"] != len(request.results)
        or ("record_ids" in event.payload and event.payload["record_ids"]
            != sorted({item.key.record_id for item in request.results}))
    ):
        raise ValueError("coverage batch Event disagrees with immutable Artifact")
    return request
