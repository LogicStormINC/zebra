"""A stdlib-only child program, passed to the configured isolated interpreter."""

# Source/data use the bounded private stdin pipe, never argv or shell interpolation.
# Neither the IPC payload nor raw stderr belongs in diagnostics.
BOOTSTRAP = """\
import json, sys
if sys.version_info[:2] != (3, 12):
    raise RuntimeError("native script requires Python 3.12")
payload = json.load(sys.stdin)
source, request = payload["source"], payload["invocation"]
namespace = {"__name__": "native_capability"}
exec(compile(source, "<native-script>", "exec"), namespace)
output = namespace["execute"](request["arguments"])
json.dump({"abi": request["abi"], "invocation_id": request["invocation_id"],
           "manifest_digest": request["manifest_digest"], "output": output},
          sys.stdout, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
"""
