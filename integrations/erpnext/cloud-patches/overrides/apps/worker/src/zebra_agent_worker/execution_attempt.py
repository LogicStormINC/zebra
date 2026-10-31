from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING

import agent_core.harness as core_harness
import zebra_agent_config
import zebra_agent_worker.execution_context as execution_context
import zebra_agent_worker.execution_continuations as execution_continuations
import zebra_agent_worker.execution_errors as errors
import zebra_agent_worker.execution_preflight as execution_preflight
import zebra_agent_worker.execution_runtime as execution_runtime
import zebra_agent_worker.execution_tool_gateway as execution_gateway
import zebra_agent_worker.provider_continuation_execution as provider_runtime
import zebra_agent_worker.runtime_setup as runtime_setup
from agent_context import LocalContextCompiler
from agent_core.application import SessionTitleService
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.plugin_authority import PluginAuthorityUnavailable
from agent_core.domain.sessions import SessionStatus
from agent_core.ports.model_gateway import ModelGatewayPort
from agent_security import LocalPolicyEngine, PolicyProfile, resolve_effective_network_profile
from zebra_agent_worker.claims import ClaimedSession
from zebra_agent_worker.context_materialization import _refresh_claim, prepare_worker_context
from zebra_agent_worker.effect_runtime import guard_worker_effects
from zebra_agent_worker.execution_completion import finish_execution, run_worker_continuation
from zebra_agent_worker.execution_errors import log_worker_failure, sequence_race_guard
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder, ExecutionInterrupted
from zebra_agent_worker.execution_finalization import ExecutedSession, WorkerExecutionError
from zebra_agent_worker.execution_preparation import (
    execution_event_view,
    finish_preparation,
)
from zebra_agent_worker.execution_recovery import (
    destroy_runtime_with_evidence,
    raise_runtime_setup_failure,
    recover_execution_inputs,
)
from zebra_agent_worker.gateway_release import GatewayRelease
from zebra_agent_worker.task_recovery import apply_bound_host_context

if TYPE_CHECKING:
    from zebra_agent_worker.execution import SessionExecutionService
    from zebra_agent_worker.execution_recovery import RecoveredExecutionInputs
    from zebra_agent_worker.progress_recovery import WorkerProgressRecovery


def execute_claimed_session_once(
    self: SessionExecutionService,
    claimed: ClaimedSession,
    *,
    started_at: datetime,
    ownership_check: Callable[[], None],
    recover_committed_completion: Callable[
        [SessionExecutionService, ClaimedSession, Callable[[], None], datetime],
        ExecutedSession | None,
    ],
    recover_execution_progress: Callable[
        [SessionExecutionService, ClaimedSession, Callable[[], None]], WorkerProgressRecovery | None
    ],
    prepare_execution_inputs: Callable[
        [
            SessionExecutionService,
            ClaimedSession,
            datetime,
            Callable[[], None],
            Callable[..., RecoveredExecutionInputs],
        ],
        RecoveredExecutionInputs,
    ],
    build_model_gateway: Callable[..., ModelGatewayPort],
) -> ExecutedSession:
    session_id = claimed.lease.session_id
    fresh = None
    if getattr(self, "_erp_fresh_enabled", False):
        if self._erp_workspace_containment is not None:
            ownership_check()
            self._erp_workspace_containment.require(
                session_id, workspace=claimed.recovery.workspace
            )
        from agent_core.domain.host_authority import HostGrantExpiredError
        from zebra_agent_worker.erp_fresh_authority import (
            EarlyFreshRefusal,
            FreshERPAuthority,
            require_early_authority,
        )

        try:
            fresh = FreshERPAuthority.for_execution(self, session_id)
        except HostGrantExpiredError:
            raise EarlyFreshRefusal("grant_expired") from None
        ownership_check()
        require_early_authority(fresh.probe(datetime.now(started_at.tzinfo)))
        from agent_storage.postgres.erp_workspace_policy import private_activation_enabled

        if private_activation_enabled(self._deployment_namespace):
            if self._workspace_resolver is None:
                raise ValueError("private ERP execution requires its native workspace resolver")
            ownership_check()
            self._workspace_resolver.resolve(
                claimed.recovery.workspace.workspace_root, session_id=session_id
            )
    if completed := recover_committed_completion(self, claimed, ownership_check, started_at):
        return completed
    if fresh is None and self._erp_workspace_containment is not None:
        ownership_check()
        self._erp_workspace_containment.require(session_id, workspace=claimed.recovery.workspace)
    worker_progress = finish_preparation(
        lambda: recover_execution_progress(self, claimed, ownership_check), ownership_check
    )
    attempt_number = worker_progress.head.state.attempt_number if worker_progress else 1
    cloud_artifacts = provider_runtime.artifact_for(self._cloud_artifact_factory, session_id)
    with sequence_race_guard("execution inputs lost a sequence race"):
        inputs = prepare_execution_inputs(
            self,
            claimed,
            started_at,
            ownership_check,
            lambda **kwargs: recover_execution_inputs(
                **kwargs, strict_dispatch_configured=self._coverage_runtime is not None
            ),
        )
    claimed = inputs.claimed
    session_events = inputs.session_events
    provider_continuation = inputs.provider_continuation
    cloud_continuation = inputs.cloud_continuation
    task, recovered_handoff = inputs.task, inputs.recovered_handoff
    active_capsule, runtime_handle, runtime = inputs.active_capsule, None, None
    execution_events = execution_event_view(
        self._event_store,
        inputs.execution_input_reader,
        claimed.lease,
        ownership_check,
        admitted_events=session_events,
    )
    trusted_local = zebra_agent_config.trusted_local_mode_enabled(self._settings)
    policy_trusted = zebra_agent_config.unrestricted_policy_mode_enabled(self._settings)
    effective_network_profile = resolve_effective_network_profile(
        task.network_profile,
        trusted_local=trusted_local,
    )
    authority_recorder, preflight_failure = execution_preflight.prepare_execution_preflight(
        recorder_factory=self._projection_recorder_factory,
        claimed=claimed,
        ownership_check=ownership_check,
        network_profile=effective_network_profile.name.value,
        has_local_artifact_store=self._artifact_payload_store is not None,
        attempt_number=attempt_number,
        started_at=started_at,
        events=session_events,
        event_store=execution_events,
    )
    if preflight_failure is not None:
        return preflight_failure
    if task.coverage_admission is not None:
        if fresh is not None:
            raise WorkerExecutionError("erp_fresh_coverage_not_activated")
        if self._coverage_runtime is None:
            raise WorkerExecutionError("coverage_unsupported")
        return self._coverage_runtime.execute(self, inputs, authority_recorder, ownership_check)
    model_gateway = execution_gateway.model_gateway(self, build_model_gateway)
    if fresh is not None:
        model_gateway = fresh.model(model_gateway)
    effect_recorder: list[DurableHarnessEventRecorder] = []
    try:
        prepared_context = prepare_worker_context(
            fresh_authority=fresh,
            store=self._context_materialization_store,
            task_binding_loader=self._task_binding_loader,
            resolver=self._execution_authority_resolver,
            static_scope=self._execution_authority_scope,
            scope_provider=self._execution_authority_scope_provider,
            recovery_service=self._recovery_service,
            event_store=execution_events,
            recorder=authority_recorder,
            claimed=claimed,
            events=session_events,
            task=task,
            active_capsule_id=(active_capsule.capsule_id if active_capsule else None),
            as_of=started_at,
            extension_store=self._extensions.snapshot_store,
            allow_mcp=self._extensions.mcp is not None,
            allow_plugins=self._settings.plugins.enabled and bool(self._extensions.plugins),
            attempt_number=attempt_number,
            execution_input_reader=inputs.execution_input_reader,
            ownership_check=ownership_check,
        )
        claimed, session_events = prepared_context.claimed, prepared_context.events
        task_binding = prepared_context.binding
        task = apply_bound_host_context(task, task_binding)
        materialized_context = prepared_context.materialization
        if fresh is not None:
            fresh.bind_recorder(
                lambda: effect_recorder[-1] if effect_recorder else authority_recorder,
                session_events,
            )
            if worker_progress is not None:
                worker_progress.fresh_authority_check = fresh.check
    except ExecutionInterrupted:
        return execution_preflight._superseded_by_control_event(authority_recorder)
    except PluginAuthorityUnavailable as exc:
        raise errors.WorkerPluginSetupUnavailable("plugin authority is unavailable") from exc
    except (RuntimeError, ValueError) as exc:
        log_worker_failure("worker_setup_failed", "context_prepare", session_id, exc)
        raise WorkerExecutionError(str(exc)) from exc
    setup_stage = "runtime_instance_binding"
    try:
        if fresh is not None:
            fresh.check("runtime")
        compatible_ids = runtime_setup.runtime_session_ids(self._task_index_store, session_id)
        bound_instance_factory = runtime_setup.bind_instance_factory(
            self._runtime_instance_factory, claimed.lease, session_events, task_binding
        )
        setup_stage = "runtime_provision"
        authority_recorder = self._projection_recorder_factory.build(
            session=claimed.recovery.session,
            workspace=claimed.recovery.workspace,
            lease=claimed.lease,
            ownership_check=ownership_check,
        )
        runtime_preparation = execution_runtime.compose_execution_runtime(
            self._settings,
            self._database_path,
            claimed=claimed,
            task=task,
            binding=task_binding,
            materialization=materialized_context,
            network_profile=effective_network_profile.name.value,
            has_capsule=active_capsule is not None,
            attempt_number=attempt_number,
            created_at=started_at,
            artifact_store=self._artifact_payload_store,
            instance_factory=bound_instance_factory,
            compatible_session_ids=compatible_ids,
            recorder=lambda: effect_recorder[-1] if effect_recorder else authority_recorder,
            trusted_local=trusted_local,
        )
        runtime, runtime_handle, authority_persisted = runtime_preparation
        if authority_persisted:
            claimed = ClaimedSession(
                recovery=self._recovery_service.recover_session(
                    session_id,
                    worker_lease=claimed.lease,
                ),
                lease=claimed.lease,
            )
        setup_stage = "tool_gateway"
        if fresh is not None:
            fresh.check("extension_materialization")
        local_tool_gateway = execution_gateway.build_execution_tool_gateway(
            self,
            task=task,
            model_gateway=model_gateway,
            session_id=session_id,
            runtime=runtime,
            runtime_handle=runtime_handle,
            cloud_artifacts=cloud_artifacts,
            trusted_local=trusted_local,
            task_binding=task_binding,
            materialized_context=materialized_context,
            extension=prepared_context.extension,
            fence=claimed.lease.fence,
            attempt_number=attempt_number,
            network_cancellation_check=authority_recorder.require_active_execution,
        )
        if fresh is not None:
            local_tool_gateway.fresh_authority_check = fresh.check
        tool_gateway = guard_worker_effects(
            local_tool_gateway,
            ledger=self._effect_ledger,
            session_id=session_id,
            recovered_handoff=recovered_handoff,
            authority_scope=(
                f"{task.workspace_root.resolve()}|{task.policy_profile}|"
                f"{effective_network_profile.name.value}"
            ),
            dispatch=self._effect_dispatch,
            local_artifacts=self._artifact_payload_store,
            lease=claimed.lease,
            recorders=effect_recorder,
            ownership_check=ownership_check,
            cloud_artifacts=cloud_artifacts,
        )
    except ExecutionInterrupted as interruption:
        destroy_runtime_with_evidence(
            runtime,
            runtime_handle,
            recorder=authority_recorder,
            created_at=started_at,
            attempt_number=attempt_number,
        )
        return execution_preflight._superseded_by_control_event(authority_recorder, interruption)
    except Exception as exc:
        raise_runtime_setup_failure(
            exc,
            runtime,
            runtime_handle,
            recorder=authority_recorder,
            stage=setup_stage,
            created_at=started_at,
            attempt_number=attempt_number,
        )
    release_gateway = GatewayRelease(
        tool_gateway, authority_recorder, started_at=started_at, attempt_number=attempt_number
    )
    try:
        if fresh is not None:
            fresh.check("context_injection")
        context_compiler = LocalContextCompiler(include_workspace=task_binding is None)
        context = core_harness.HarnessContext(
            task=execution_context.harness_task_for_recovered(
                task,
                network_profile=effective_network_profile,
                tool_gateway=tool_gateway,
                memory_store=self._memory_store,
                personalization_store=self._personalization_store,
                materialization=materialized_context,
            ),
            session=claimed.recovery.session,
            attempt=core_harness.HarnessAttempt(number=attempt_number, started_at=started_at),
        )
        setup_stage = "continuation_recovery"
        with sequence_race_guard("continuation start lost a sequence race"):
            if fresh is not None:
                claimed = _refresh_claim(
                    authority_recorder, self._recovery_service, claimed, ownership_check
                )
            claimed, continuations = execution_continuations.recover_and_start_continuations(
                claimed,
                session_events=session_events,
                event_store=execution_events,
                recovery_service=self._recovery_service,
                started_at=started_at,
                recorder=authority_recorder,
                cleanup=release_gateway,
                child_result_verifier=execution_continuations.build_child_result_verifier(
                    self._delegation_store, self._projection_store
                ),
                attempt_number=attempt_number,
            )
        continuation = continuations.approved
        clarification = continuations.clarification
        child_wakeup = continuations.child_wakeup
        client_wakeup = continuations.client_effect
        setup_stage = "continuation_recorder"
        recorder = self._projection_recorder_factory.build(
            session=claimed.recovery.session,
            workspace=claimed.recovery.workspace,
            lease=claimed.lease,
            ownership_check=ownership_check,
        )
        release_gateway.recorder = recorder
        effect_recorder.append(recorder)
        if not any((continuation, clarification, child_wakeup, client_wakeup)) and (
            worker_progress is None
            or not worker_progress.head.state.attempt_started
            or recorder.session.status is SessionStatus.READY
        ):
            recorder.append(
                EventType.HARNESS_ATTEMPT_STARTED,
                EventActor.HARNESS,
                {"attempt_number": attempt_number},
                created_at=started_at,
            )
        context = replace(context, session=recorder.session)
        setup_stage = "orchestrator_build"
        orchestrator = execution_context.build_worker_orchestrator(
            model_gateway=model_gateway,
            fresh_authority_check=fresh.check if fresh else None,
            tool_gateway=tool_gateway,
            policy_engine=LocalPolicyEngine(
                profile=PolicyProfile(task.policy_profile),
                network_profile=effective_network_profile,
                web_search_endpoint=self._settings.web_search_endpoint,
                web_pipeline_v2=self._settings.web_pipeline_v2,
                trusted_local=policy_trusted,
                additional_read_only_tools=local_tool_gateway.read_only_tools,
                additional_write_tools=local_tool_gateway.authorized_write_tools,
                additional_approval_tools=local_tool_gateway.approval_required_tools,
            ),
            context_compiler=context_compiler,
            cloud_continuation=cloud_continuation,
            recorder=recorder,
            event_store=self._event_store,
            lifecycle_store=self._context_lifecycle_store,
            cloud_artifacts=cloud_artifacts,
            local_continuation_store=self._provider_continuation_store,
            session_id=session_id,
            provider_continuation=provider_continuation,
            invocation_policy=task.model_invocation_policy,
            public_output_policy=self._settings.public_output,
            worker_progress=worker_progress,
            transient_output=(
                self._transient_output_factory(worker_progress, claimed.lease)
                if self._transient_output_factory and worker_progress
                else None
            ),
            user_input=task.user_input,
            attempt_number=attempt_number,
        )
        setup_stage = "continuation_run"
        attempt_result = run_worker_continuation(
            orchestrator,
            context,
            continuation=continuation,
            clarification=clarification,
            child_wakeup=child_wakeup,
            client_effect=client_wakeup,
            release_gateway=release_gateway,
        )
        return finish_execution(
            recorder=recorder,
            attempt_result=attempt_result,
            memory_extraction_service=self._memory_extraction_service,
            memory_promotion_service=self._memory_promotion_service,
            title_service=SessionTitleService(model_gateway),
            event_store=execution_events,
            cloud_memory_store=self._cloud_memory_store,
            deployment_namespace=self._deployment_namespace,
            projection_store=self._projection_store,
            workspace_store=self._workspace_store,
            task_index_store=self._task_index_store,
            session_id=session_id,
            started_at=started_at,
            interaction_mode=task.interaction_mode,
            attempt_number=attempt_number,
        )
    except ExecutionInterrupted as interruption:
        release_gateway()
        return execution_preflight._superseded_by_control_event(
            release_gateway.recorder, interruption
        )
    except BaseException as exc:
        log_worker_failure("worker_execution_failed", setup_stage, session_id, exc)
        if (cleanup_error := release_gateway()) is not None:
            exc.add_note(f"tool gateway cleanup failed: {type(cleanup_error).__name__}")
        raise
