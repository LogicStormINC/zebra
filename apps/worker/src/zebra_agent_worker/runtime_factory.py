from hashlib import sha1
from pathlib import Path
from tempfile import gettempdir

from agent_core.ports.runtime import RuntimeClass, RuntimeLimits, RuntimePort, SandboxSpec
from agent_runtime import (
    LocalRuntime,
    OciRuntime,
    OsSandboxRuntime,
    os_sandbox_engine,
    require_workspace_quota,
)
from agent_runtime.adapters.oci_engine import PinnedOciEngine
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_worker.runtime_instances import BoundInstanceFactory


def build_runtime(
    settings: ZebraAgentSettings,
    database_path: Path,
    *,
    workspace_root: Path,
    network_profile: str,
    session_id: str = "local-session",
    attempt_number: int = 1,
    instance_factory: BoundInstanceFactory | None = None,
) -> RuntimePort:
    runtime_root = _runtime_root(database_path)
    if settings.runtime.require_workspace_quota:
        require_workspace_quota(
            workspace_root,
            maximum_bytes=settings.runtime.workspace_quota_mb * 1024 * 1024,
        )
    runtime_class = RuntimeClass(settings.runtime.runtime_class)
    if runtime_class is RuntimeClass.TRUSTED_LOCAL:
        return LocalRuntime(snapshot_root=runtime_root)
    engine = (
        os_sandbox_engine() if runtime_class is RuntimeClass.OS_SANDBOX else settings.runtime.engine
    )
    spec = SandboxSpec(
        runtime_class=runtime_class,
        image=settings.runtime.image,
        workspace_root=str(workspace_root.resolve()),
        session_id=session_id,
        attempt_number=attempt_number,
        engine=engine,
        runtime_handler=settings.runtime.gvisor_runtime,
        network_profile=network_profile,
        container_uid=settings.runtime.container_uid,
        container_gid=settings.runtime.container_gid,
        limits=RuntimeLimits(
            cpu_count=settings.runtime.cpu_count,
            memory_mb=settings.runtime.memory_mb,
            pids=settings.runtime.pids,
            tmpfs_mb=settings.runtime.tmpfs_mb,
            max_output_bytes=settings.runtime.max_output_bytes,
            max_execution_seconds=settings.runtime.max_execution_seconds,
            workspace_quota_mb=(
                settings.runtime.workspace_quota_mb
                if settings.runtime.require_workspace_quota
                else None
            ),
        ),
    )
    if runtime_class is RuntimeClass.OS_SANDBOX:
        return OsSandboxRuntime(spec, snapshot_root=runtime_root)
    pinned = None
    lifecycle = None
    if settings.deployment == "cloud":
        if instance_factory is None:
            raise ValueError("cloud OCI runtime requires a fenced instance lifecycle")
        pinned = pin_cloud_engine(settings)
        lifecycle = instance_factory(pinned.identity)
    from subprocess import run

    return OciRuntime(
        spec,
        engine_command=(settings.runtime.engine,),
        gvisor_runtime=settings.runtime.gvisor_runtime,
        snapshot_root=runtime_root,
        runner=run if pinned is None else pinned,
        instance_lifecycle=lifecycle,
    )


def pin_cloud_engine(settings: ZebraAgentSettings) -> PinnedOciEngine:
    """Provision and cleanup use the same explicit endpoint/configuration resolver."""
    return PinnedOciEngine(settings.runtime.engine)


def _runtime_root(database_path: Path) -> Path:
    database_key = sha1(str(database_path.resolve()).encode("utf-8")).hexdigest()[:12]
    return Path(gettempdir()) / "zebra-agent-runtime" / database_key
