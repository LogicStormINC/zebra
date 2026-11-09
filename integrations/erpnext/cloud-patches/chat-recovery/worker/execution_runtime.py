"""Compose eager or attempt-owned deferred runtime from trusted Worker state."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from agent_core.domain.context_materialization import ContextMaterialization
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_core.ports.artifact_payload_store import ArtifactPayloadStorePort
from agent_core.ports.runtime import RuntimeHandle, RuntimePort
from agent_runtime.deferred import DeferredRuntime
from zebra_agent_config import ZebraAgentSettings
from zebra_agent_worker import runtime_authority, runtime_setup
from zebra_agent_worker.claims import ClaimedSession
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.runtime_instances import BoundInstanceFactory
from zebra_agent_worker.task_recovery import RecoveredTask


def can_defer_runtime(
    settings: ZebraAgentSettings,
    *,
    claimed: ClaimedSession,
    binding: TaskBindingSnapshot | None,
    materialization: ContextMaterialization | None,
    network_profile: str,
    has_capsule: bool,
) -> bool:
    workspace = claimed.recovery.workspace
    return (
        settings.deployment == "cloud"
        and settings.runtime.defer_provision
        and settings.runtime.runtime_class in {"gvisor", "oci-rootless"}
        and binding is not None
        and materialization is not None
        and workspace.runtime_spec_digest is None
        and workspace.runtime_name is None
        and workspace.snapshot_id is None
        and workspace.snapshot_path is None
        and network_profile != "setup-only"
        and not has_capsule
        and not settings.mcp_servers
        and not any(
            (
                settings.skill_roots,
                settings.skill_roots_system,
                settings.skill_roots_admin,
                settings.skill_roots_repo,
            )
        )
    )


def compose_execution_runtime(
    settings: ZebraAgentSettings,
    database_path: Path,
    *,
    claimed: ClaimedSession,
    task: RecoveredTask,
    binding: TaskBindingSnapshot | None,
    materialization: ContextMaterialization | None,
    network_profile: str,
    has_capsule: bool,
    attempt_number: int,
    created_at: datetime,
    artifact_store: ArtifactPayloadStorePort | None,
    instance_factory: BoundInstanceFactory | None,
    compatible_session_ids: tuple[str, ...],
    recorder: Callable[[], DurableHarnessEventRecorder],
    trusted_local: bool,
) -> tuple[RuntimePort, RuntimeHandle | None, bool]:
    def check() -> None:
        recorder().require_active_execution()

    from agent_storage.postgres.erp_chat_readonly import enabled as chat_enabled

    if chat_enabled(binding.host_capability.namespace_id if binding else None):
        if (
            binding is None
            or materialization is None
            or task.attachments
            or task.image_attachments
            or task.coverage_admission is not None
            or has_capsule
            or task.network_profile.name.value != "none"
            or task.policy_profile != "read_only"
            or task.history_session_ids
            or task.mcp_allowlist
            or task.skill_components
        ):
            raise ValueError("ERP readonly chat inputs exceed the admitted surface")

        def refuse_runtime():
            check()
            raise RuntimeError("ERP readonly chat has no workspace runtime")

        return DeferredRuntime(refuse_runtime, check=check), None, False

    prepared: runtime_setup.PreparedRuntime | None = None
    authority_persisted = False
    deferred = can_defer_runtime(
        settings,
        claimed=claimed,
        binding=binding,
        materialization=materialization,
        network_profile=network_profile,
        has_capsule=has_capsule,
    )

    def prepare() -> tuple[RuntimePort, RuntimeHandle]:
        nonlocal prepared
        check()
        runtime, prepared = runtime_setup.build_prepared_runtime(
            settings,
            database_path,
            workspace_root=task.workspace_root,
            network_profile=network_profile,
            session_id=claimed.lease.session_id,
            attempt_number=attempt_number,
            artifact_store=artifact_store,
            created_at=created_at,
            instance_factory=instance_factory,
            compatible_session_ids=compatible_session_ids,
            cancellation_check=check,
        )
        return runtime, prepared.handle

    def ready(handle: RuntimeHandle) -> None:
        nonlocal authority_persisted
        assert prepared is not None
        check()
        runtime_setup.require_matching_runtime_authority(
            handle,
            None if trusted_local else recorder().workspace.runtime_spec_digest,
            prepared.compatible_authority_digests,
        )
        check()
        authority_persisted = runtime_authority.persist_runtime_authority(
            recorder(), handle.authority, created_at=datetime.now(UTC) if deferred else created_at
        )
        check()

    if deferred:
        return DeferredRuntime(prepare, ready=ready, check=check), None, False
    runtime, handle = prepare()
    try:
        ready(handle)
    except BaseException as error:
        cleanup = runtime_setup.destroy_runtime(runtime, handle)
        if cleanup is not None:
            error.add_note(f"runtime cleanup failed: {type(cleanup).__name__}")
        raise
    return runtime, handle, authority_persisted
