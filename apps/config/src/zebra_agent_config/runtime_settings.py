"""Runtime configuration shared by local and explicit cloud composition."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeSettings:
    runtime_class: str = "trusted-local"
    engine: str = "docker"
    gvisor_runtime: str = "runsc"
    image: str = ""
    cpu_count: float = 2.0
    memory_mb: int = 2048
    pids: int = 256
    tmpfs_mb: int = 512
    max_output_bytes: int = 1_048_576
    max_execution_seconds: float = 900.0
    container_uid: int = 65532
    container_gid: int = 65532
    require_workspace_quota: bool = False
    workspace_quota_mb: int = 10_240
    defer_provision: bool = False


def validate_profile_contract(
    *,
    profile: str,
    database_url: str,
    runtime: RuntimeSettings,
    development_unrestricted: bool,
) -> None:
    if development_unrestricted and profile != "cloud":
        raise ValueError(
            "ZEBRA_DEVELOPMENT_UNRESTRICTED=true is allowed only for ZEBRA_PROFILE=cloud"
        )
    if profile not in {"cloud", "production"}:
        return
    if runtime.runtime_class != "gvisor" and not (profile == "cloud" and development_unrestricted):
        raise ValueError(f"ZEBRA_PROFILE={profile} requires ZEBRA_RUNTIME_CLASS=gvisor")
    if not database_url.startswith(("postgresql://", "postgres://")):
        raise ValueError(f"ZEBRA_PROFILE={profile} requires a PostgreSQL DSN")
