"""One current certificate boundary for its exact canonical report bytes."""

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_core.domain.coverage_report import CoverageReport
from agent_core.domain.coverage_validation import (
    AcceptedCoverageUnit,
    CoverageCertificate,
    expected_units,
)
from agent_core.domain.events import EventActor, SessionEvent

from agent_storage.postgres.coverage_artifacts import read_artifact, read_manifest
from agent_storage.postgres.coverage_model_checkpoint import check_checkpoint_retention
from agent_storage.postgres.coverage_model_source import task_policy
from agent_storage.postgres.coverage_transactions import lock_run, validate_event_fence


def read_certified_report(
    store: Any, namespace: str, run_id: str, *, now: datetime,
    check_authority: Callable[[], None],
    authority_expires_at: datetime | None = None,
) -> tuple[CoverageCertificate, str, bytes] | None:
    """Keep the existing gate; never re-read ordinary Artifacts after authorization.

    ponytail: original proof verification remains O(n) per read. Returning the
    verified bytes avoids a second ungoverned read, not the original proof scan.
    """
    if authority_expires_at is not None and (
        not isinstance(authority_expires_at, datetime)
        or authority_expires_at.utcoffset() is None
        or now >= authority_expires_at
    ):
        raise CoverageRefusedError(CoverageRefusalReason.AUTHORITY_INVALID)
    binding = store._binding(namespace, run_id)
    check_authority()
    if not binding.snapshot.as_of <= now < binding.snapshot.expires_at:
        raise ValueError("coverage certificate has expired")
    with store._database.connect() as connection:
        row = connection.execute(
            """SELECT cancelled FROM coverage_runs WHERE deployment_namespace=%s
               AND namespace=%s AND run_id=%s""",
            (store._deployment, namespace, run_id),
        ).fetchone()
        if row is None or row["cancelled"]:
            raise ValueError("coverage run is cancelled or unavailable")
        events = connection.execute(
            """SELECT * FROM session_events WHERE deployment_namespace=%s AND session_id=%s
               AND event_type='coverage_report_certified' AND payload->>'namespace'=%s
               AND payload->>'run_id'=%s LIMIT 2""",
            (store._deployment, binding.session_id, namespace, run_id),
        ).fetchall()
        if events:
            if len(events) != 1:
                raise ValueError("ambiguous certificate authority")
            issued = SessionEvent.model_validate(events[0])
            validate_event_fence(issued.payload)
            certificate = CoverageCertificate.model_validate(issued.payload["certificate"])
            policy = task_policy(connection, store._deployment, binding)
            if issued.actor is not EventActor.SYSTEM or certificate.created_at > issued.created_at:
                raise ValueError("certificate has no lawful original issuance")
            if policy is not None and not (
                policy.started_at <= certificate.created_at <= issued.created_at < policy.deadline
            ):
                raise ValueError("certificate exceeded original issuance deadline")
            records = read_manifest(store._artifacts, binding)
            accepted_rows = connection.execute(
                """SELECT result FROM coverage_units WHERE deployment_namespace=%s
                   AND namespace=%s AND run_id=%s ORDER BY ordinal LIMIT 200001""",
                (store._deployment, namespace, run_id),
            ).fetchall()
            if len(accepted_rows) > 200000 or any(
                item["result"] is None for item in accepted_rows
            ):
                raise ValueError("certified coverage is incomplete")
            accepted = tuple(
                AcceptedCoverageUnit.model_validate(item["result"]) for item in accepted_rows
            )
            expected = expected_units(binding.contract, records, max_units=200000)
            if len(accepted) != len(expected) or {item.key for item in accepted} != set(expected):
                raise ValueError("certified coverage exact membership conflicts")
            store._verify_result_sources(connection, binding, accepted)
    if not events:
        return None
    if len(events) != 1:
        raise ValueError("ambiguous certificate authority")
    event = events[0]
    certificate = CoverageCertificate.model_validate(event["payload"]["certificate"])
    if (
        certificate.contract_digest != binding.contract.digest
        or certificate.manifest_digest != binding.snapshot.manifest_digest
        or certificate.event_watermark != event["sequence"]
        or certificate.expires_at <= now
    ):
        raise ValueError("certificate binding conflicts")
    ref = event["payload"]["report_ref"]
    body = read_artifact(store._artifacts, ref, certificate.report_digest, binding.session_id)
    report = CoverageReport.model_validate(json.loads(body))
    if report.canonical_bytes != body:
        raise ValueError("coverage report is not canonical")
    report.validate_certificate(binding, certificate, watermark=event["sequence"])
    report.validate_for(binding, accepted)
    check_authority()
    with store._database.connect() as connection:
        lock_run(connection, store._deployment, binding, None)
        deadlines: list[datetime] = []
        store._check_publication_lifecycle(
            connection, binding, ref, certificate.report_digest, deadlines
        )
        check_authority()
        row = connection.execute(
            """SELECT cancelled,clock_timestamp() AS now FROM coverage_runs
               WHERE deployment_namespace=%s AND namespace=%s AND run_id=%s""",
            (store._deployment, namespace, run_id),
        ).fetchone()
        if row is None or row["cancelled"]:
            raise ValueError("coverage run is cancelled or unavailable")
        if not binding.snapshot.as_of <= row["now"] < min(
            binding.snapshot.expires_at, certificate.expires_at
        ):
            raise ValueError("coverage certificate has expired")
        final_now = check_checkpoint_retention(connection, deadlines)
        if authority_expires_at is not None and final_now >= authority_expires_at:
            raise CoverageRefusedError(CoverageRefusalReason.AUTHORITY_INVALID)
        return certificate, ref, body
