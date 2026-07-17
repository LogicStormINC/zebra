from hashlib import sha1
from pathlib import Path
from tempfile import gettempdir

from agent_core.ports.runtime import RuntimeClass, RuntimeLimits, RuntimePort, SandboxSpec
from agent_runtime import LocalRuntime, OciRuntime
from zebra_agent_config import ZebraAgentSettings


def build_runtime(
    settings: ZebraAgentSettings,
    database_path: Path,
    *,
    workspace_root: Path,
    network_profile: str,
    session_id: str = "local-session",
    attempt_number: int = 1,
) -> RuntimePort:
    runtime_root = _runtime_root(database_path)
    runtime_class = RuntimeClass(settings.runtime.runtime_class)
    if runtime_class is RuntimeClass.TRUSTED_LOCAL:
        return LocalRuntime(snapshot_root=runtime_root)
    spec = SandboxSpec(
        runtime_class=runtime_class,
        image=settings.runtime.image,
        workspace_root=str(workspace_root.resolve()),
        session_id=session_id,
        attempt_number=attempt_number,
        engine=settings.runtime.engine,
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
        ),
    )
    return OciRuntime(
        spec,
        engine_command=(settings.runtime.engine,),
        gvisor_runtime=settings.runtime.gvisor_runtime,
        snapshot_root=runtime_root,
    )


def _runtime_root(database_path: Path) -> Path:
    database_key = sha1(str(database_path.resolve()).encode("utf-8")).hexdigest()[:12]
    return Path(gettempdir()) / "zebra-agent-runtime" / database_key
