"""Read-only isolation readiness; does not create a sandbox or run a Task."""

import json
from pathlib import Path
from subprocess import TimeoutExpired

from agent_core.ports.runtime import RuntimeCapabilityError, RuntimeClass
from agent_runtime import OciRuntime
from agent_runtime.capability_checks import require_runtime_capabilities
from zebra_agent_config import ZebraAgentSettings, load_settings

from zebra_agent_worker.runtime_factory import build_runtime_spec, pin_cloud_engine


def check_runtime(settings: ZebraAgentSettings) -> None:
    if settings.runtime.runtime_class not in {RuntimeClass.GVISOR, RuntimeClass.OCI_ROOTLESS}:
        return  # The explicitly selected local development runtime is not an OCI sandbox.
    runtime = OciRuntime(
        build_runtime_spec(
            settings, workspace_root=Path("/tmp/zebra-runtime-preflight"),
            network_profile="none", session_id="runtime-preflight", attempt_number=1,
        ),
        engine_command=(settings.runtime.engine,),
        gvisor_runtime=settings.runtime.gvisor_runtime,
        runner=pin_cloud_engine(settings),
    )
    require_runtime_capabilities(runtime)


def main() -> int:
    try:
        check_runtime(load_settings())
    except (RuntimeCapabilityError, ValueError, TimeoutExpired, OSError) as error:
        print(json.dumps({
            "status": "unavailable", "code": "runtime_unavailable",
            "detail": str(error) if isinstance(error, RuntimeCapabilityError | ValueError)
            else "OCI engine readiness probe failed",
        }))
        return 1
    print(json.dumps({"status": "ready"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
