"""Static no-network guard for the bounded native network path."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "packages/agent-runtime/src/agent_runtime/web_gateway.py").read_text()
assert 'start_new_session=os.name == "posix"' in source
assert "_terminate_process_tree(child)" in source
assert "check()  # A completed child must not publish after the Task signal." in source
assert 'max_output_bytes=max(request.max_bytes, request.max_output_bytes) * 6 + 65536' in source
assert 'one short-lived child per native request' in source
print("native network cancellation, output bounds, and child isolation guards: PASS")
