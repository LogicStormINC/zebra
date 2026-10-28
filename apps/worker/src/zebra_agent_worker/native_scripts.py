"""Compose task-bound native capabilities; rules and execution live in packages."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from agent_core.application.native_script import (
    NativeScriptInvocationService,
    NativeScriptUnavailable,
)
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.native_script import NativeScript
from agent_core.domain.runtime_bundle_json import json_digest
from agent_core.domain.script_bundle import ScriptBinding, ScriptRuntimeAssembly
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_core.ports.event_store import BoundedSessionEventReadPort, EventStorePort
from agent_core.ports.runtime import RuntimePort, SandboxSpec
from agent_runtime.native_script_journal import EventScriptJournal
from agent_runtime.native_script_runtime import ScopedNativeScriptRunner
from agent_storage.postgres.native_script_authority import (
    NativeScriptAuthority,
    PostgresScriptJournal,
)
from agent_tools.native_script import NativeScriptTools
from zebra_agent_config import ZebraAgentSettings
from zebra_agent_config.bundle_settings import load_execution_catalog
from zebra_agent_config.native_script import ScriptExecutionCatalog

from zebra_agent_worker.bundle_assembly import task_assembly
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.runtime_factory import (
    build_runtime,
    build_runtime_spec,
    script_workspace_parent,
)
from zebra_agent_worker.runtime_instances import BoundInstanceFactory
from zebra_agent_worker.task_recovery import RecoveredTask


def approved_scripts(
    settings: ZebraAgentSettings, assembly: ScriptRuntimeAssembly
) -> ScriptExecutionCatalog:
    runner = assembly.native_scripts.runner
    if (
        runner.runtime_class == "gvisor"
        and settings.runtime.image.partition("@")[2] != assembly.bundle.manifest.engine.image.digest
    ):
        raise NativeScriptUnavailable("INCOMPATIBLE_NATIVE_SCRIPT_IMAGE")
    if any(
        item.manifest.timeout_seconds > min(30, settings.runtime.max_execution_seconds)
        or item.manifest.max_output_bytes > min(32768, settings.runtime.max_output_bytes)
        for item in assembly.native_scripts.bindings
    ):
        raise NativeScriptUnavailable("INCOMPATIBLE_NATIVE_SCRIPT_LIMITS")
    catalog = load_execution_catalog(settings.runtime_bundle_config)
    if (
        not isinstance(catalog, ScriptExecutionCatalog)
        or catalog.resolve_scripts(assembly.script_bundle) != assembly
        or assembly.native_scripts.runner.runtime_class != settings.runtime.runtime_class
        or (settings.deployment == "cloud" and assembly.native_scripts.runner.mode != "production")
    ):
        raise NativeScriptUnavailable("INCOMPATIBLE_NATIVE_SCRIPT_WORKER")
    return catalog


def prepare_native_scripts(
    *,
    settings: ZebraAgentSettings,
    database_path: Path,
    task: RecoveredTask,
    binding: TaskBindingSnapshot | None,
    events: EventStorePort,
    recorder: Callable[[], DurableHarnessEventRecorder],
    instance_factory: BoundInstanceFactory | None,
    attempt_number: int,
) -> NativeScriptTools | None:
    assembly = task_assembly(task)
    if not isinstance(assembly, ScriptRuntimeAssembly):
        return None
    snapshot = task.definition_snapshot
    current = recorder()
    if (
        snapshot is None
        or binding is None
        or current.worker_mutation_authority is None
        or not isinstance(events, BoundedSessionEventReadPort)
        or binding.agent_capability_ceiling.definition_snapshot_digest != snapshot.snapshot_digest
        or binding.host_capability.namespace_id != assembly.bundle.manifest.scope.namespace_id
        or binding.host_capability.authority_issuer
        != assembly.bundle.manifest.scope.authority_issuer
    ):
        raise NativeScriptUnavailable("NATIVE_SCRIPT_BINDING_UNAVAILABLE")
    approved_scripts(settings, assembly)
    authority = NativeScriptAuthority(events, binding)
    context = binding.host_capability.host_context
    assert context is not None
    if any(
        not set(item.scopes) <= set(context.scopes) for item in assembly.native_scripts.bindings
    ):
        raise NativeScriptUnavailable("NATIVE_SCRIPT_SCOPE_DENIED")

    def check() -> None:
        recorder().require_active_execution()
        authority.check()

    def authorize(item: ScriptBinding) -> NativeScript:
        if item not in assembly.native_scripts.bindings:
            raise NativeScriptUnavailable("NATIVE_SCRIPT_BINDING_CONFLICT")
        check()
        try:
            return approved_scripts(settings, assembly).script_for(item.manifest.digest)
        except (ValueError, PermissionError, OSError):
            raise NativeScriptUnavailable("NATIVE_SCRIPT_APPROVAL_UNAVAILABLE") from None

    def append(event_type: EventType, actor: EventActor, payload: dict[str, object]) -> object:
        return authority.checked(lambda: recorder().append(event_type, actor, payload))

    journal = EventScriptJournal(events, current.session.session_id, append, check)

    def factory(workspace: Path) -> tuple[RuntimePort, SandboxSpec]:
        spec = build_runtime_spec(
            settings,
            workspace_root=workspace,
            network_profile="none",
            session_id=str(current.session.session_id),
            attempt_number=attempt_number,
        )
        spec = replace(
            spec,
            workspace_writable=False,
            limits=replace(
                spec.limits,
                max_output_bytes=min(spec.limits.max_output_bytes, 32768),
                max_execution_seconds=min(spec.limits.max_execution_seconds, 30),
            ),
        )
        runtime = build_runtime(
            settings,
            database_path,
            workspace_root=workspace,
            network_profile="none",
            session_id=str(current.session.session_id),
            attempt_number=attempt_number,
            instance_factory=instance_factory,
            spec_override=spec,
        )
        return runtime, spec

    service = NativeScriptInvocationService(
        task_id=binding.task_id,
        snapshot_digest="sha256:" + snapshot.snapshot_digest,
        owner_fence=json_digest(
            current.worker_mutation_authority.lease_fence.model_dump(mode="json")
        ),
        journal=PostgresScriptJournal(journal),
        authorize=authorize,
        runner=lambda: ScopedNativeScriptRunner(
            assembly.native_scripts.runner,
            factory,
            workspace_parent=script_workspace_parent(settings),
        ),
    )

    def commit_answer(action: Callable[[], None]) -> None:
        recorder().require_active_execution()
        approved_scripts(settings, assembly)
        authority.commit(action)

    return NativeScriptTools(service, assembly.native_scripts.bindings, commit_answer=commit_answer)
