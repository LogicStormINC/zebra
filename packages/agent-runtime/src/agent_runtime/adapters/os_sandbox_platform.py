import json
import platform
from pathlib import Path

from agent_core.ports.runtime import RuntimeCapabilityError

_SAFE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


def os_sandbox_engine(system: str | None = None) -> str:
    name = system or platform.system()
    if name == "Darwin":
        return "sandbox-exec"
    if name == "Linux":
        return "bwrap"
    raise RuntimeCapabilityError(f"os-sandbox is unsupported on {name or 'unknown OS'}")


def build_probe_command(*, system: str, executable: str) -> tuple[str, ...]:
    if system == "Darwin":
        return (
            executable,
            "-p",
            "(version 1)(deny default)(allow process*)(allow file-read*)",
            "/usr/bin/true",
        )
    return (
        executable,
        "--die-with-parent",
        "--unshare-all",
        "--ro-bind",
        "/",
        "/",
        "--",
        "/bin/true",
    )


def build_execution_command(
    *,
    system: str,
    executable: str,
    command: tuple[str, ...],
    workspace: Path,
    cwd: Path,
    workspace_writable: bool,
) -> tuple[str, ...]:
    if system == "Darwin":
        return (
            executable,
            "-p",
            _seatbelt_profile(workspace, workspace_writable=workspace_writable),
            "/usr/bin/env",
            "-i",
            f"HOME={workspace}",
            f"TMPDIR={workspace}",
            f"PATH={_SAFE_PATH}",
            *command,
        )
    args = [
        executable,
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
        "--tmpfs",
        "/",
    ]
    for source in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc"):
        if Path(source).exists():
            args.extend(("--dir", source, "--ro-bind", source, source))
    args.extend(("--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp"))
    for parent in reversed(workspace.parents[:-1]):
        args.extend(("--dir", str(parent)))
    bind = "--bind" if workspace_writable else "--ro-bind"
    args.extend(
        (
            bind,
            str(workspace),
            str(workspace),
            "--chdir",
            str(cwd),
            "--clearenv",
            "--setenv",
            "HOME",
            str(workspace),
            "--setenv",
            "TMPDIR",
            "/tmp",
            "--setenv",
            "PATH",
            _SAFE_PATH,
            "--",
            *command,
        )
    )
    return tuple(args)


def _seatbelt_profile(workspace: Path, *, workspace_writable: bool) -> str:
    workspace_literal = json.dumps(str(workspace))
    write_rule = ""
    if workspace_writable:
        write_rule = f"(allow file-write* (subpath {workspace_literal}))"
    return (
        '(version 1)(deny default)(import "system.sb")(allow process*)'
        f"(allow file-read* (subpath {workspace_literal}))"
        f"{write_rule}"
        "(deny network*)"
    )
