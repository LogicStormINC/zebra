"""Operator acceptance: real sandbox, shared bytes, quota; no model or user Turn."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from agent_core.ports.runtime import RuntimeExecutionRequest
from agent_runtime import OciRuntime, require_workspace_quota
from zebra_agent_config import load_settings
from zebra_agent_worker.runtime_factory import build_runtime_spec, pin_cloud_engine

settings = load_settings()
root = Path(os.environ["ZEBRA_WORKSPACE_VOLUME_ROOT"])
quota = require_workspace_quota(
    root, maximum_bytes=settings.runtime.workspace_quota_mb * 1024 * 1024,
)
with TemporaryDirectory(prefix="gvisor-acceptance-", dir=root) as workspace:
    # The VM share remaps UID ownership. Only this disposable acceptance directory
    # permits its sandbox UID to write; existing business paths are never chmodded.
    os.chmod(workspace, 0o777)
    session_id = "acceptance-" + uuid4().hex
    runtime = OciRuntime(
        build_runtime_spec(settings, workspace_root=Path(workspace),
                           network_profile="none", session_id=session_id, attempt_number=1),
        engine_command=(settings.runtime.engine,),
        gvisor_runtime=settings.runtime.gvisor_runtime,
        runner=pin_cloud_engine(settings),
    )
    handle = None
    try:
        handle = runtime.provision()
        assert handle.authority is not None
        assert handle.authority.runtime_class.value == "gvisor"
        result = runtime.execute(RuntimeExecutionRequest(
            command=("python", "-c",
                     "from pathlib import Path; Path('shared.marker').write_text('accepted'); "
                     "print('gvisor execution accepted')"),
            timeout_seconds=10,
        ))
        assert result.succeeded, (result.failure_reason, result.stderr)
        assert Path(workspace, "shared.marker").read_text() == "accepted"
        print(result.stdout.strip())
        print(f"shared workspace and enforced quota accepted: {quota.capacity_bytes} bytes")
    finally:
        if handle is not None:
            runtime.destroy(handle)
        else:
            runtime.destroy_session(session_id)
