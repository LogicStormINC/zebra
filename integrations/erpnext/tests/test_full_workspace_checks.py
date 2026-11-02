"""python3 tests/test_full_workspace_checks.py; operator configuration only, no allocation."""

import importlib.util
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "cloud-patches/operator"))
spec = importlib.util.spec_from_file_location(
    "operator_under_test", root / "cloud-patches/operator/private_workspace_operator.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
config = dict(
    helper_image="sha256:" + "a" * 64,
    helper_network="erpnext-full-qa-proof",
    generation="cloud114-qa",
    helper_hostname="authority.qa.example",
    readonly_dsn="not-connected",
    host_tool_shared_secret="not-sent",
)
proof = module.NativeProof(config)
assert (
    proof.network == "erpnext-full-qa-proof" and proof.module == "full_workspace_proof" and proof.qa
)
for update in [
    dict(generation="unknown"),
    dict(helper_network="erpnext-private-proof"),
    dict(helper_image="mutable:latest"),
    dict(helper_hostname="127.0.0.1"),
]:
    try:
        module.NativeProof({**config, **update})
    except ValueError:
        pass
    else:
        raise AssertionError("unsafe operator profile accepted")
legacy = module.NativeProof(
    {**config, "generation": "native105", "helper_network": "erpnext-private-proof"}
)
assert legacy.module == "zebra_agent_worker.erp_private_workspace_proof" and not legacy.qa
print("immutable helper, fixed generation/network and legacy compatibility passed; no allocation")

# Cold Python imports + a bounded5s native check cannot fit a fixed7s wall budget.
# Keep the original absolute20s deadline and reserve5s for forced helper cleanup.

old_output, old_run = module.subprocess.check_output, module.subprocess.run
calls = []


def native_output(argv, *, input, timeout, stderr):
    request = json.loads(input)
    calls.append(timeout)
    assert 7 < timeout <= module.REQUEST_SECONDS - 5
    return json.dumps(
        dict(
            session_id=request["session_id"],
            workspace_id=request["workspace_id"],
            nonce=request["nonce"],
            identity="a" * 64,
            state="pending",
            expires_at=time.time() + 30,
        )
    ).encode()


module.subprocess.check_output = native_output
module.subprocess.run = lambda *a, **k: SimpleNamespace(returncode=0)
try:
    assert proof(str(__import__("uuid").uuid4()), str(__import__("uuid").uuid4()))[1] == "pending"
    token = module.DEADLINE.set(time.monotonic() + 4)
    try:
        try:
            proof(str(__import__("uuid").uuid4()), str(__import__("uuid").uuid4()))
        except TimeoutError:
            pass
        else:
            raise AssertionError("cleanup reservation bypassed")
    finally:
        module.DEADLINE.reset(token)
    assert len(calls) == 1
finally:
    module.subprocess.check_output, module.subprocess.run = old_output, old_run
print("PASS helper uses bounded remaining budget, preserves fresh proof and reserves cleanup time")
