"""Strict native execution; no exploratory Harness, runtime, or narration fallback."""

from collections.abc import Callable
from contextlib import ExitStack, nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from agent_core.application.coverage_admission import validate_coverage_admission
from agent_core.application.coverage_checks import PublishedCoverageRunner
from agent_core.application.coverage_executor import CoverageExecutor
from agent_core.application.coverage_semantic import semantic_check
from agent_core.domain.coverage_contracts import CoverageRefusalReason as Reason
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import TaskId
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_core.harness.models import HarnessAttemptOutcome, HarnessAttemptResult
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.effect_dispatch import effect_input
from agent_integrations import build_model_gateway
from agent_integrations.coverage_model import SemanticCoverageModel
from agent_integrations.coverage_model_derivation import derive_semantic_observation
from agent_integrations.coverage_model_invocation import CoverageModelInvocation
from agent_integrations.coverage_model_policy import REVIEWER_PROFILE
from agent_integrations.coverage_snapshot import HostCoverageSnapshotAdapter
from agent_integrations.coverage_snapshot_artifacts import CoverageArtifacts
from agent_integrations.coverage_snapshot_source import HostCoverageSnapshotSource
from agent_integrations.host_credentials import ConfiguredHmacHostCredentialResolver
from agent_integrations.host_tools.http import HttpHostToolTransport
from agent_integrations.openai_compatible import OpenAICompatibleModelGateway
from agent_security import LocalPolicyEngine, PolicyProfile
from agent_storage.postgres.command_wakeup_recovery import continue_coverage_command
from agent_storage.postgres.coverage import PostgresCoverageStore
from agent_storage.postgres.coverage_authority import PostgresCoverageAuthority
from agent_storage.postgres.coverage_recovery_preparation import CoverageRecoveryDeferred
from agent_storage.postgres.coverage_transactions import lock_run
from agent_storage.postgres.leases import assert_current_lease_fence
from agent_storage.postgres.task_admission import load_session_task_binding
from agent_storage.postgres.work_unit import postgres_work_unit
from psycopg.errors import LockNotAvailable, QueryCanceled

from zebra_agent_worker.cloud_effect_payloads import CloudEffectPayloadCoordinator
from zebra_agent_worker.coverage_bootstrap import bootstrap_cloud_coverage
from zebra_agent_worker.coverage_certified import finish_certified_execution, read_issued_report
from zebra_agent_worker.coverage_composition import CloudCoverageRuntime, load_official_model_policy
from zebra_agent_worker.coverage_effect import CloudCoverageEffectInvoke
from zebra_agent_worker.coverage_recovery_preparation import NativeCoverageRecoveryCheck
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.execution_finalization import ExecutedSession
from zebra_agent_worker.execution_recovery import RecoveredExecutionInputs
from zebra_agent_worker.host_gateway_resolution import (
    frozen_or_discovered_manifest,
    resolve_pinned_gateway,
)
from zebra_agent_worker.provider_configuration import model_provider_settings


def execute_cloud_coverage(
    runtime: CloudCoverageRuntime,
    service: Any,
    inputs: RecoveredExecutionInputs,
    recorder: DurableHarnessEventRecorder,
    ownership_check: Callable[[], None],
) -> ExecutedSession:
    """Compose existing native components under the current lease heartbeat.

    ponytail: serial batches reuse native progress wakes; full-C admission and
    exact cumulative originals may still refuse, never a guessed average size.
    """
    task, lease = inputs.task, inputs.claimed.lease
    loaded = (
        service._task_binding_loader(lease.session_id) if service._task_binding_loader else None
    )
    if (
        not isinstance(loaded, TaskBindingSnapshot)
        or service._cloud_artifact_factory is None
        or service._cloud_memory_store is None
        or inputs.provider_continuation is not None
        or inputs.recovered_handoff is not None
    ):
        raise CoverageRefusedError(Reason.UNSUPPORTED)
    pinned = TaskBindingSnapshot.model_validate(effect_input(loaded), strict=True)
    host = pinned.host_capability.host_context
    entry_time = datetime.now(UTC)
    if host is None or host.expires_at is None or entry_time >= host.expires_at:
        raise CoverageRefusedError(Reason.AUTHORITY_INVALID)
    host_expiry = host.expires_at
    admission = validate_coverage_admission(
        task.coverage_admission, host_context=host, now=entry_time
    )
    if host != task.host_context or admission.model_profile != REVIEWER_PROFILE:
        raise CoverageRefusedError(Reason.AUTHORITY_INVALID)
    origins = [e for e in inputs.session_events if e.event_type is EventType.TASK_PREPARED]
    if not origins or any(e.payload.get("coverage_admission") is None for e in origins):
        raise CoverageRefusedError(Reason.UNSUPPORTED)
    with runtime.metadata._database.connect() as connection:
        native = connection.execute(
            """SELECT r.accepted_event_id FROM command_handoff_receipts r
               JOIN session_command_pending p ON p.deployment_namespace=r.deployment_namespace
                 AND p.accepted_event_id=r.accepted_event_id
               WHERE r.deployment_namespace=%s AND r.session_id=%s
                 AND r.status='accepted' AND r.handled_event_id IS NULL AND p.status='pending'
                 AND r.wake_generation=p.current_generation AND r.control_plane_epoch=%s
                 AND r.fencing_token=%s AND r.owner_instance_id=%s LIMIT 2""",
            (
                runtime.deployment_namespace,
                lease.session_id,
                lease.fence.control_plane_epoch,
                lease.fence.fencing_token,
                lease.fence.owner_instance_id,
            ),
        ).fetchall()
        if len(native) != 1:
            raise CoverageRefusedError(Reason.UNSUPPORTED)
    deadline = origins[0].created_at + timedelta(seconds=admission.max_runtime_seconds)
    with runtime.metadata._database.connect() as connection:
        issued = connection.execute(
            "SELECT * FROM session_events WHERE deployment_namespace=%s AND session_id=%s "
            "AND event_type='coverage_report_certified' LIMIT 2",
            (runtime.deployment_namespace, lease.session_id),
        ).fetchall()
    if len(issued) > 1 or (
        issued and not origins[0].created_at <= issued[0]["created_at"] < deadline
    ):
        raise CoverageRefusedError(Reason.AUTHORITY_INVALID)
    snapshot_id: str | None = None
    execution_authority = PostgresCoverageAuthority.prepare(
        runtime.metadata._database, lease.session_id, pinned, lease.fence,
        lambda session: load_session_task_binding(
            runtime.dsn, deployment_namespace=runtime.deployment_namespace, session_id=session,
        ),
    )

    def check_local_native() -> None:
        ownership_check()
        if execution_authority is not None:
            try:
                latest = execution_authority.check(
                    deadline=host_expiry if issued else min(host_expiry, deadline),
                )
            except ValueError as error:
                raise CoverageRefusedError(Reason.AUTHORITY_INVALID) from error
            if latest > recorder.session.current_sequence:
                recorder.project_persisted_tail()
        else:
            recorder.project_persisted_tail()
        current_gateway = resolve_pinned_gateway(host, service._egress_registry, credential)
        if (
            current_gateway is None
            or gateway is None
            or current_gateway.endpoint != gateway.endpoint
            or current_gateway.workload_identity != gateway.workload_identity
            or current_gateway.shared_secret != gateway.shared_secret
        ):
            raise CoverageRefusedError(Reason.AUTHORITY_INVALID)
        current = pinned if execution_authority is not None else (
            service._task_binding_loader(lease.session_id)
        )
        if (
            not isinstance(current, TaskBindingSnapshot)
            or TaskBindingSnapshot.model_validate(effect_input(current), strict=True) != pinned
            or host is None
            or host.expires_at is None
            or datetime.now(UTC) >= host.expires_at
        ):
            raise CoverageRefusedError(Reason.AUTHORITY_INVALID)
        if not issued and datetime.now(UTC) >= deadline:
            raise CoverageRefusedError(Reason.BUDGET_EXCEEDED)
        if execution_authority is None:
            with runtime.metadata._database.connect() as connection:
                assert_current_lease_fence(
                    connection, runtime.deployment_namespace, lease.session_id, lease.fence
                )
                active = connection.execute(
                    "SELECT active_segment_id FROM agent_tasks "
                    "WHERE deployment_namespace=%s AND task_id=%s",
                    (runtime.deployment_namespace, pinned.task_id),
                ).fetchone()
                if active is None or active["active_segment_id"] != lease.session_id:
                    raise CoverageRefusedError(Reason.AUTHORITY_INVALID)
        if recorder.session.status not in {SessionStatus.READY, SessionStatus.RUNNING}:
            raise CoverageRefusedError(Reason.CANCELLED)

    def check_local() -> None:
        # DB-only phase: fresh authority and recorder tail/projection share the
        # exact transaction, then release it before Host/model/object I/O.
        with postgres_work_unit(runtime.metadata._database):
            check_local_native()

    def check_external() -> None:
        if snapshot_id is not None:
            source.host.authority_check(host)
            source._live(frozen_descriptor)
            if source.host.manifest != manifest:
                raise CoverageRefusedError(Reason.AUTHORITY_INVALID)
            descriptor = source._get_descriptor(snapshot_id, host, source.host.budget(host))
            if descriptor != frozen_descriptor:
                raise CoverageRefusedError(Reason.SCOPE_MISMATCH)

    def check() -> None:
        check_local()
        check_external()

    def authority() -> WorkerMutationAuthority:
        recorder.project_persisted_tail()
        result = recorder.worker_mutation_authority
        if result is None:
            raise CoverageRefusedError(Reason.UNSUPPORTED)
        return result

    with ExitStack() as cleanup:
        if not service._settings.host_tool_shared_secret:
            raise CoverageRefusedError(Reason.UNSUPPORTED)
        credential = ConfiguredHmacHostCredentialResolver(service._settings.host_tool_shared_secret)
        gateway = resolve_pinned_gateway(host, service._egress_registry, credential)
        if gateway is None:
            raise CoverageRefusedError(Reason.UNSUPPORTED)
        manifest = frozen_or_discovered_manifest(
            gateway, host, pinned.host_capability.manifest_digest, service._frozen_manifest_loader
        )
        client = cleanup.enter_context(
            httpx.Client(verify=True, trust_env=False, follow_redirects=False)
        )
        gateway.transport = HttpHostToolTransport(client=client)
        artifacts = service._cloud_artifact_factory(lease.session_id)
        effect = CloudCoverageEffectInvoke(
            payloads=CloudEffectPayloadCoordinator(
                lease.session_id, artifacts, service._effect_dispatch
            ),
            gateway=gateway,
            admission=admission,
            binding=pinned,
            context=host,
            fence=lease.fence,
            authority=authority,
            policy=LocalPolicyEngine(
                profile=PolicyProfile(task.policy_profile),
                network_profile=task.network_profile,
                additional_write_tools=frozenset({"dataset.snapshot.create"}),
            ),
            check_authority=check,
            next_event=recorder.prepare,
            accept_event=recorder.accept_persisted_event,
        )
        source = HostCoverageSnapshotSource(
            session_id=lease.session_id,
            authority=host,
            history_ref=admission.history_ref,
            manifest=manifest,
            invoke=gateway.invoke,
            admitted_effect_invoke=effect,
        )
        check()
        settings = replace(model_provider_settings(service._settings), max_retries=0)

        def gateway_factory() -> OpenAICompatibleModelGateway:
            result = build_model_gateway(settings)
            if type(result) is not OpenAICompatibleModelGateway:
                raise CoverageRefusedError(Reason.UNSUPPORTED)
            return result

        initial_gateway = gateway_factory()
        proof = (
            None
            if issued
            else load_official_model_policy(
                api_key=initial_gateway._api_key, deadline=deadline, check_authority=check
            )
        )
        recorder.append(
            EventType.HARNESS_ATTEMPT_STARTED,
            EventActor.HARNESS,
            {
                "attempt_number": 1
                + sum(
                    e.event_type is EventType.HARNESS_ATTEMPT_STARTED for e in inputs.session_events
                )
            },
        )
        # A recovery reuses the authoritative manifest's original run/snapshot.
        with runtime.metadata._database.connect() as connection:
            existing = connection.execute(
                "SELECT payload->>'run_id' AS run_id,"
                "payload->'binding'->'snapshot'->>'snapshot_id' AS snapshot_id "
                "FROM session_events WHERE deployment_namespace=%s AND session_id=%s "
                "AND event_type='coverage_manifest_committed' ORDER BY sequence LIMIT 2",
                (runtime.deployment_namespace, lease.session_id),
            ).fetchall()
        if len(existing) > 1:
            raise CoverageRefusedError(Reason.UNSUPPORTED)
        run_id = existing[0]["run_id"] if existing else f"coverage-{lease.session_id}"
        recovered_snapshot = existing[0]["snapshot_id"] if existing else None
        boot = bootstrap_cloud_coverage(
            dsn=runtime.dsn,
            deployment_namespace=runtime.deployment_namespace,
            metadata=runtime.metadata,
            objects=runtime.objects,
            source=source,
            host_authority=host,
            admission=admission,
            task_id=TaskId(UUID(pinned.task_id)),
            session_id=lease.session_id,
            run_id=run_id,
            fence=lease.fence,
            authority=authority,
            check_authority=check,
            sync_events=recorder.project_persisted_tail,
            snapshot_id=recovered_snapshot,
        )
        snapshot_id = boot.binding.snapshot.snapshot_id
        frozen_descriptor = source._get_descriptor(snapshot_id, host, source.host.budget(host))
        # Bootstrap has finished its independent admission/publication checks.
        # All subsequent Artifact reads use this same current execution boundary.
        boot.artifacts.check_authority = check
        if execution_authority is not None:
            boot.artifacts.check_local_authority = check_local
            boot.artifacts.check_external_authority = check_external
        boot.artifacts.reuse_verified_payloads = admission.validation_mode == "final_certification"
        store = PostgresCoverageStore(
            runtime.dsn,
            deployment_namespace=runtime.deployment_namespace,
            artifacts=boot.artifacts,
            supported_model_profiles=(REVIEWER_PROFILE,),
            model_observation_deriver=derive_semantic_observation,
        )
        if issued:
            with runtime.metadata._database.connect() as connection:
                lock_run(connection, runtime.deployment_namespace, boot.binding, lease.fence)
                certificate, report_ref = read_issued_report(
                    store,
                    connection,
                    boot.binding,
                    SessionEvent.model_validate(issued[0]),
                    [],
                    check,
                )
                assert_current_lease_fence(
                    connection, runtime.deployment_namespace, lease.session_id, lease.fence
                )
            return finish_certified_execution(
                service,
                runtime,
                recorder,
                lease,
                certificate,
                report_ref,
                initial_gateway,
                origins[0].created_at,
                task.interaction_mode,
            )
        part_count = sum(len(r.parts) for r in boot.records)
        if (
            proof is None
            or admission.max_model_calls < part_count
            or admission.max_model_tokens < part_count * proof.context_window
            or admission.execution_budget.max_attempts < part_count + len(boot.records)
            or admission.execution_budget.max_input_bytes
            < 2 * sum(p.byte_length for r in boot.records for p in r.parts)
        ):
            raise CoverageRefusedError(Reason.BUDGET_EXCEEDED)
        policy = store.initialize_model_budget(boot.binding, fence=lease.fence)
        invocation = CoverageModelInvocation(
            binding=boot.binding,
            artifacts=CoverageArtifacts(boot.artifacts, lease.session_id, nullcontext()),
            budget_store=store,
            original_policy=policy,
            fresh_fence=lambda: lease.fence,
            check_authority=check,
            gateway_factory=gateway_factory,
            trusted_proof=proof,
        )
        adapter = HostCoverageSnapshotAdapter(
            session_id=lease.session_id,
            authority=host,
            history_ref=admission.history_ref,
            manifest=manifest,
            invoke=gateway.invoke,
            artifacts=boot.artifacts,
            publication_lock=nullcontext(),
            admitted_effect_invoke=effect,
        )
        prepared = adapter.prepare(snapshot_id, authority=host)
        runner = PublishedCoverageRunner(
            (semantic_check(REVIEWER_PROFILE),),
            model=SemanticCoverageModel(
                model_profile=REVIEWER_PROFILE, check_authority=check, invoke_or_replay=invocation
            ),
        )
        executor = CoverageExecutor(
            binding=boot.binding,
            records=boot.records,
            store=store,
            artifacts=boot.artifacts,
            read=prepared.read,
            runner=runner,
            budget=admission.execution_budget,
            check_authority=check,
        )
        work = service._settings.coverage_work
        expected, accepted = executor.execute_batch(
            fence=lease.fence, limit=work.max_units,
            max_input_bytes=work.max_input_bytes, max_seconds=work.max_milliseconds / 1000,
            batch_commits=True,
        )
        if accepted != expected:
            recorder.project_persisted_tail()
            try:
                with runtime.metadata._database.connect() as connection:
                    continue_coverage_command(
                        connection,
                        runtime.deployment_namespace,
                        lease.session_id,
                        lease.fence,
                        NativeCoverageRecoveryCheck(runtime, service, execution_authority),
                    )
                summary = "Bounded coverage batch accepted; native continuation queued."
            except (CoverageRecoveryDeferred, QueryCanceled, LockNotAvailable):
                summary = "Bounded coverage batch accepted; awaiting fresh native recovery proof."
            result = HarnessAttemptResult(
                outcome=HarnessAttemptOutcome.SUSPENDED,
                summary=summary,
                metadata={"stop_reason": "coverage_batch", "run_id": boot.binding.run_id},
            )
            # The native command remains unhandled under RUNNING. Its next
            # generation owns a fresh lease; only a certified report closes it.
            return ExecutedSession(recorder.session, recorder.events, result)
        certificate, report_ref = executor.publish_report(store, fence=lease.fence)
        return finish_certified_execution(
            service,
            runtime,
            recorder,
            lease,
            certificate,
            report_ref,
            initial_gateway,
            origins[0].created_at,
            task.interaction_mode,
        )
