"""Read an already issued report under native locks, never issue a new certificate."""

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from agent_core.application import SessionTitleService
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.coverage_report import CoverageReport
from agent_core.domain.coverage_validation import CoverageCertificate
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
from agent_storage.postgres.coverage import PostgresCoverageStore
from agent_storage.postgres.coverage_artifacts import read_artifact
from agent_storage.postgres.coverage_model_checkpoint import check_checkpoint_retention
from agent_storage.postgres.coverage_model_source import task_policy
from agent_storage.postgres.coverage_transactions import validate_event_fence

from zebra_agent_worker.execution_completion import finish_execution
from zebra_agent_worker.execution_finalization import ExecutedSession


def read_issued_report(
    store: PostgresCoverageStore,
    connection: Any,
    binding: CoverageRunBinding,
    event: SessionEvent,
    deadlines: list[datetime],
    check_authority: Callable[[], None],
) -> tuple[CoverageCertificate, str]:
    """Reuse storage's semantic/lifecycle gate and core's canonical report checks.

    The caller holds lock_run. Historical issuance may outlive its execution
    deadline; current source authority and every original retention still apply.
    """
    policy = task_policy(connection, store._deployment, binding)
    validate_event_fence(event.payload)
    certificate = CoverageCertificate.model_validate(event.payload["certificate"])
    if (
        event.event_type is not EventType.COVERAGE_REPORT_CERTIFIED
        or event.actor is not EventActor.SYSTEM
        or event.session_id != binding.session_id
        or event.payload["namespace"] != binding.namespace
        or event.payload["run_id"] != binding.run_id
        or policy is None
        or not policy.started_at <= certificate.created_at <= event.created_at < policy.deadline
    ):
        raise ValueError("strict recovery report has no lawful original issuance")
    check_authority()
    ref = event.payload["report_ref"]
    store._check_publication_lifecycle(
        connection, binding, ref, certificate.report_digest, deadlines
    )
    body = read_artifact(store._artifacts, ref, certificate.report_digest, binding.session_id)
    report = CoverageReport.model_validate(json.loads(body))
    report.validate_for(binding, store._accepted_results(connection, binding))
    report.validate_certificate(binding, certificate, watermark=event.sequence)
    if body != report.canonical_bytes:
        raise ValueError("strict recovery report is not canonical")
    check_authority()
    check_checkpoint_retention(connection, deadlines)
    return certificate, ref


def finish_certified_execution(
    service: Any,
    runtime: Any,
    recorder: Any,
    lease: Any,
    certificate: CoverageCertificate,
    report_ref: str,
    gateway: Any,
    started_at: datetime,
    interaction_mode: Any,
) -> ExecutedSession:
    recorder.project_persisted_tail()
    result = HarnessAttemptResult(
        outcome=HarnessAttemptOutcome.COMPLETED,
        summary="Certified coverage report available.",
        metadata={
            "coverage_report_ref": report_ref,
            "coverage_certificate": certificate.model_dump(mode="json"),
        },
    )
    return finish_execution(
        recorder=recorder,
        attempt_result=result,
        memory_extraction_service=service._memory_extraction_service,
        memory_promotion_service=service._memory_promotion_service,
        title_service=SessionTitleService(gateway),
        event_store=service._event_store,
        cloud_memory_store=service._cloud_memory_store,
        deployment_namespace=runtime.deployment_namespace,
        projection_store=service._projection_store,
        workspace_store=service._workspace_store,
        task_index_store=service._task_index_store,
        session_id=lease.session_id,
        started_at=started_at,
        interaction_mode=interaction_mode,
    )
