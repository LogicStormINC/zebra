"""Fresh native child imports avoid unrelated public namespace aggregates."""

import json
import subprocess
import sys

import pytest


def fresh(code: str) -> dict:
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True,
                               text=True, check=True, timeout=15)
    return json.loads(completed.stdout)


@pytest.mark.parametrize("module", ["agent_runtime.web_gateway", "agent_runtime.web_search"])
def test_web_import_does_not_load_harness_or_storage(module):
    loaded = fresh(f"import importlib,json,sys;importlib.import_module({module!r});"
                   "print(json.dumps(list(sys.modules)))")
    assert "agent_runtime.harness" not in loaded
    assert not any(name.startswith("agent_storage") for name in loaded)
    assert not any(name.startswith("agent_core.application") for name in loaded)


@pytest.mark.parametrize("module,count", [("agent_core", 47), ("agent_core.domain", 244),
                                          ("agent_core.ports", 143), ("agent_runtime", 71)])
def test_public_exports_and_submodule_from_import_remain_compatible(module, count):
    result = fresh(f"""
import importlib,json
package=importlib.import_module({module!r})
assert len(package.__all__)=={count}
assert set(package.__all__)<=set(dir(package))
exports=importlib.import_module({module!r}+'._public_exports')
assert package.__all__==exports.__all__
for name in package.__all__:
 value=getattr(package,name)
 assert value is getattr(exports,name)
 assert value is getattr(package,name)
namespace={{}}
exec('from '+{module!r}+' import *',namespace)
assert all(namespace[name] is getattr(exports,name) for name in package.__all__)
try:getattr(package,'missing_public_export')
except AttributeError:pass
else:raise AssertionError('unknown public export accepted')
print(json.dumps({{'count':len(package.__all__)}}))
""")
    assert result["count"] == count


def test_root_submodule_import_does_not_load_runtime_aggregate():
    loaded = fresh("import json,sys;from agent_runtime import web_gateway;"
                   "print(json.dumps(list(sys.modules)))")
    assert "agent_runtime.harness" not in loaded
    assert "agent_runtime._public_exports" not in loaded
