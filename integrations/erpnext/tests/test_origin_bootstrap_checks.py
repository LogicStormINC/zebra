"""python3 tests/test_origin_bootstrap_checks.py; execute actual bootstrap without Frappe."""

import ast
import sys
import types
from pathlib import Path
from types import SimpleNamespace

source = Path(__file__).resolve().parents[1] / "zebra_erpnext/api.py"
node = next(
    n
    for n in ast.parse(source.read_text()).body
    if isinstance(n, ast.FunctionDef) and n.name == "bootstrap"
)
node.decorator_list = []
f = SimpleNamespace(
    get_list=lambda *a, **k: [],
    defaults=SimpleNamespace(get_global_default=lambda *a: None),
    conf={},
)
# The newer administrator branch imports inside bootstrap; keep its actual authorization.
admin = types.ModuleType("zebra_erpnext.admin_mode")
admin.enabled = lambda user: False
sys.modules["zebra_erpnext.admin_mode"] = admin
sys.path.insert(0, str(source.parents[1]))
ns = {
    "frappe": f,
    "cloud": SimpleNamespace(principal=lambda: "user"),
    "chat": SimpleNamespace(MODEL_OPTIONS=[], REASONING_OPTIONS=[]),
}
exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), ns)
for settings, expected in [
    ({"origin": "https://old.test", "browser_origin": "https://new.test"}, "https://new.test/desk"),
    ({"origin": "https://old.test"}, "https://old.test/desk"),
    ({}, "/desk"),
]:
    f.conf["zebra_agent"] = settings
    result = ns["bootstrap"]()
    assert result["https_url"] == expected, (result["https_url"], expected)
    assert not {"origin", "browser_origin", "host_secret", "signing_key"} & result.keys()
print(
    "PASS actual bootstrap uses configured page origin, legacy fallback, and no credential exposure"
)
