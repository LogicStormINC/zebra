"""python3 tests/test_full_workspace_checks.py; operator configuration only, no allocation."""

import importlib.util
import sys
from pathlib import Path

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
