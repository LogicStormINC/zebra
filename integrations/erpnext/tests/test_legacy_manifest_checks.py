"""Execute actual manifest schema builder with actual exported business constants."""

import ast
import sys
import types
from pathlib import Path

root = Path(__file__).resolve().parents[1]
business = types.ModuleType("zebra_erpnext.business")
ns = {}
for node in ast.parse((root / "zebra_erpnext/business.py").read_text()).body:
    if isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id in {"SCHEMAS", "AGGREGATE_METRICS"} for t in node.targets
    ):
        exec(compile(ast.Module(body=[node], type_ignores=[]), "business.py", "exec"), ns)
for name, value in ns.items():
    if name != "__builtins__":
        setattr(business, name, value)
sys.modules["zebra_erpnext.business"] = business
node = next(
    n
    for n in ast.parse((root / "zebra_erpnext/gateway.py").read_text()).body
    if isinstance(n, ast.FunctionDef) and n.name == "business_arguments_schema"
)
exec(compile(ast.Module(body=[node], type_ignores=[]), "gateway.py", "exec"), ns)
schema = ns["business_arguments_schema"]({"aggregate"})
assert business.AGGREGATE_METRICS == {"count", "sum", "avg", "min", "max"}
count, numeric = schema["anyOf"]
assert "field" not in count["properties"] and count["properties"]["metric"]["enum"] == ["count"]
assert "field" in numeric["required"] and set(numeric["properties"]["metric"]["enum"]) == {
    "sum",
    "avg",
    "min",
    "max",
}
assert ns["business_arguments_schema"]({"create", "update", "submit"})["properties"]["doctype"]
print(
    "PASS actual legacy manifest resolves shared metrics, "
    "count/numeric and proposal argument contracts"
)
