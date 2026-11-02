"""Run with `uv run python tests/compose/cloud_ha_e1/check_metering.py`."""

import json
import runpy
import shutil
import tempfile
from hashlib import sha256
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from metering import CONTRACT, encode, measure_request, measured_usage

request = {"model": "deepseek-v4-pro", "messages": [{"role": "user", "content": "中文\0"}],
           "max_tokens": 1024}
wire = encode(request)
proof = measure_request(wire)
assert proof.exact_body == wire and proof.request_digest == sha256(wire).hexdigest()
assert proof.input_upper_bound == len(wire) and proof.output_cap == 1024
assert proof.counter_contract == CONTRACT
message = {"role": "assistant", "content": "完成"}
usage = measured_usage(request, message)
assert usage == {"prompt_tokens": len(wire), "completion_tokens": len(encode(message)),
                 "total_tokens": len(wire) + len(encode(message))}
for invalid in (b"[]", b"null", b"\xff", json.dumps(request).encode(),
                encode(dict(request, max_tokens=True)), encode(dict(request, max_tokens=0)),
                b" " * (4 * 1024 * 1024 + 1)):
    try:
        measure_request(invalid)
    except (ValueError, TypeError):
        pass
    else:
        raise AssertionError("invalid/counterfactual wire accepted")
try:
    measured_usage(dict(request, max_tokens=1), message)
except ValueError:
    pass
else:
    raise AssertionError("fixture output exceeded actual request cap")
print("Synthetic canonical UTF-8 byte meter: exact request, usage, cap and negatives passed.")

# Exercise the actual provider function, not a separate meter-only copy.
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    source = Path(__file__).parent
    for name in ("model.py", "metering.py"):
        shutil.copyfile(source / name, root / name)
    shutil.copyfile(
        source.parent / "cloud_effect_composition/fake_model.py", root / "fake_model.py"
    )
    module = runpy.run_path(str(root / "model.py"))
    provider = module["completion"]
    request["tools"] = [{"type": "function"}]
    result = provider(request)
    message = result["choices"][0]["message"]
    assert result["usage"] == measured_usage(request, message)
    assert json.loads(message["tool_calls"][0]["function"]["arguments"]) == {"command": ["pwd"]}
print("Actual synthetic provider uses the same meter and read-only tool contract.")

# Oversized Content-Length must reject before reading an absent body.
server = ThreadingHTTPServer(("127.0.0.1", 0), module["Handler"])
thread = Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    for body, headers, status in (
        (b"", {"Content-Length": str(4 * 1024 * 1024 + 1)}, 400),
        (encode(dict(request, max_tokens=1)), {}, 400),
        (encode(request), {}, 200),
    ):
        connection = HTTPConnection(*server.server_address, timeout=2)
        try:
            connection.request("POST", "/chat/completions", body, headers)
            response = connection.getresponse()
            assert response.status == status
            payload = json.loads(response.read())
            if status == 200:
                assert payload["usage"] == measured_usage(
                    request, payload["choices"][0]["message"]
                )
        finally:
            connection.close()
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
    assert not thread.is_alive()
print("Actual fixture HTTP cap rejection, bounded body and usage response passed.")
