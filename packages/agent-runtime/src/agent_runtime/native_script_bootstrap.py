"""A stdlib-only child program, passed to the configured isolated interpreter."""

# Source and data are separate argv entries, never shell interpolation. They must
# not be logged: script source can be proprietary and arguments can be business data.
BOOTSTRAP = """\
import json, sys
if sys.version_info[:2] != (3, 12):
    raise RuntimeError("native script requires Python 3.12")
source, request = sys.argv[1], json.loads(sys.argv[2])
namespace = {"__name__": "native_capability"}
exec(compile(source, "<native-script>", "exec"), namespace)
output = namespace["execute"](request["arguments"])
json.dump({"abi": request["abi"], "invocation_id": request["invocation_id"],
           "manifest_digest": request["manifest_digest"], "output": output},
          sys.stdout, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
"""
