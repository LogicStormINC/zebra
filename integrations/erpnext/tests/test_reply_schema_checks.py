"""python3 tests/test_reply_schema_checks.py; actual published manifest, no network."""

import ast
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

root = Path(__file__).resolve().parents[1]
namespace = {}
source = ast.parse((root / "zebra_erpnext/business.py").read_text())
for n in source.body:
    if isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id in {"SCHEMAS", "READS", "WRITES", "AGGREGATE_METRICS"}
        for t in n.targets
    ):
        exec(compile(ast.Module(body=[n], type_ignores=[]), "business-contract", "exec"), namespace)
business = ModuleType("zebra_erpnext.business")
for k in ["SCHEMAS", "READS", "WRITES", "AGGREGATE_METRICS"]:
    setattr(business, k, namespace[k])
runtime = ModuleType("zebra_erpnext.runtime")
runtime.LEGACY = "native105"
runtime.FULL = "cloud114"
runtime.release = lambda d: d.runtime_ref
admin = ModuleType("zebra_erpnext.admin_mode")
admin.SCOPE = "erpnext.admin"
admin.granted = lambda *a: False
sys.modules.update(
    {
        "zebra_erpnext.business": business,
        "zebra_erpnext.runtime": runtime,
        "zebra_erpnext.admin_mode": admin,
    }
)
sys.path.insert(0, str(root))
doc = SimpleNamespace(runtime_ref="cloud114")
scope = {
    "frappe": SimpleNamespace(get_doc=lambda *a: doc),
    "raw": lambda x: x,
    "delegated": lambda: (SimpleNamespace(conversation="owned"), {}),
    "cloud": SimpleNamespace(config=lambda: {}),
}
tree = ast.parse((root / "zebra_erpnext/gateway.py").read_text())
for name in ["business_arguments_schema", "manifest"]:
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), "gateway", "exec"
        ),
        scope,
    )
scope["CHAT_READS"] = {
    "get",
    "query",
    "query_page",
    "aggregate",
    "report_describe",
    "workflow_transitions",
}
result = scope["manifest"]()
read = next(t for t in result["tools"] if t["name"] == "erpnext.read")
a = read["argumentProperties"]["arguments"]
assert a.get("additionalProperties") is False, "full Cloud arguments remain untyped"
assert "count" in a["properties"]["metric"]["enum"] and a["anyOf"]
assert set(read["argumentProperties"]["operation"]["enum"]) == business.READS, (
    "full mode functionality narrowed"
)
assert all(t["parallelSafe"] is False for t in result["tools"]), (
    "parallel execution requires separate proof"
)
print("PASS full read schema reuses validator fields and retains operations and current safety")
