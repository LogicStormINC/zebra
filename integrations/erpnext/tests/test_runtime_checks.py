"""python3 tests/test_runtime_checks.py; no ERP/Cloud/model request."""

import json
import sys
import types
from pathlib import Path


class Rejected(Exception):
    pass


frappe = types.ModuleType("frappe")
frappe.throw = lambda message, *args: (_ for _ in ()).throw(Rejected(message))
sys.modules["frappe"] = frappe
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
runtime = __import__("zebra_erpnext", fromlist=("runtime",)).runtime

base = {
    "base_url": "https://legacy.example",
    "runtimes": {
        "cloud114": {
            "base_url": "https://full.example",
            "namespace_id": "erpnext-full",
            "enabled": True,
            "acceptance_passed": True,
            "capability_profiles": ["business", "research", "analysis"],
            "capabilities": {"extensions": True},
        }
    },
}
old = types.SimpleNamespace(runtime_ref=None, preferences_json="{}")
new = types.SimpleNamespace(runtime_ref="cloud114", preferences_json="{}")
assert runtime.release(old) == "native105"
assert runtime.settings(old, base) is base
assert runtime.new_release(base) == "cloud114"
assert runtime.new_release({"runtimes": {"cloud114": {"enabled": True}}}) == "native105"
assert runtime.settings(new, base)["namespace_id"] == "erpnext-full"
assert runtime.profile(new, base)["network_profile"] == "none"
new.preferences_json = json.dumps(
    {"capability_profile": "analysis", "extension_selection": {"skills": ["one"], "mcp": ["two"]}}
)
assert runtime.profile(new, base)["policy_profile"] == "workspace_write"
assert runtime.selections(new) == {"skills": ["one"], "mcp": ["two"]}
for value in [
    dict(capability_profile="arbitrary-shell"),
    dict(extension_selection={"url": "https://evil"}),
    dict(extension_selection={"skills": ["same", "same"]}),
    dict(extension_selection={"mcp": ["x"] * 17}),
]:
    new.preferences_json = json.dumps(value)
    try:
        runtime.profile(new, base)
        runtime.selections(new)
    except Rejected:
        pass
    else:
        raise AssertionError("invalid capability configuration accepted")
assert runtime.profile(old, base) == runtime.PROFILES["business"]
assert not runtime.enabled(old, base, "extensions")
print("runtime release, profile and selection safety: passed")
