"""python3 tests/test_full_workspace_refusal_checks.py; no model/HTTP/allocation."""

import hashlib
import hmac
import importlib.util
import io
import json
import logging
import os
import sys
import tempfile
import time
import types
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloud-patches/operator"))
spec = importlib.util.spec_from_file_location(
    "allocator_test", ROOT / "cloud-patches/operator/private_workspace_operator.py"
)
operator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(operator)
key = b"x" * 32
wid = str(uuid4())
body = dict(
    session_id=str(uuid4()),
    workspace_id=wid,
    request_id=str(uuid5(UUID(wid), "erpnext-private-workspace-v1")),
    nonce=str(uuid4()),
    timestamp=int(time.time()),
    operation="verify",
)
packet = dict(body=body, mac=hmac.new(key, operator.canonical(body), hashlib.sha256).hexdigest())


class Allocator:
    worker_uid = os.getuid()
    authenticate = operator.Allocator.authenticate

    def __init__(self):
        self.manifest = {"nonces": {}, "volumes": {}}
        self.calls = 0

    def locked(self):
        return nullcontext()

    def read(self):
        return self.manifest

    def save(self, value):
        self.manifest = value

    def ensure(self, value):
        self.calls += 1
        raise TimeoutError("PRIVATE INPUT MUST NOT BE LOGGED")


a = Allocator()
logs = io.StringIO()
handler = logging.StreamHandler(logs)
logging.getLogger().addHandler(handler)
reply = operator.allocator_reply(a, key, operator.canonical(packet) + b"\n", os.getuid())
mac = reply.pop("mac")
assert (
    reply["ok"] is False
    and reply["code"] == "workspace_preparation_timeout"
    and reply["nonce"] == body["nonce"]
)
assert hmac.compare_digest(
    mac, hmac.new(key, operator.canonical(reply), hashlib.sha256).hexdigest()
)
assert "PRIVATE INPUT" not in logs.getvalue() and "TimeoutError" in logs.getvalue()
for malformed in [
    b"{}\n",
    b"x" * 4097 + b"\n",
    operator.canonical({**packet, "mac": "forged"}) + b"\n",
]:
    assert "mac" not in operator.allocator_reply(a, key, malformed, os.getuid())
assert a.calls == 1
logging.getLogger().removeHandler(handler)

# Existing dependencies are stubbed only to import the client; no real volume path is touched.
runtime = types.ModuleType("agent_runtime")
quota = types.ModuleType("agent_runtime.workspace_quota")
quota.require_workspace_quota = lambda *a, **k: (_ for _ in ()).throw(
    AssertionError("must not verify a refused allocation")
)
sys.modules["agent_runtime"] = runtime
sys.modules["agent_runtime.workspace_quota"] = quota
os.environ["ZEBRA_WORKSPACE_VOLUME_ROOT"] = "/var/lib/zebra/erpnext-full-workspaces"
spec = importlib.util.spec_from_file_location(
    "client_test", ROOT / "deploy/runtime/full_workspace_client.py"
)
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


class Socket:
    mode = "valid"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def settimeout(self, *a):
        pass

    def connect(self, *a):
        pass

    def sendall(self, data):
        b = json.loads(data)["body"]
        v = dict(
            ok=False,
            nonce=b["nonce"],
            code="workspace_capacity_exhausted",
            error="private_workspace_refused",
        )
        if self.mode == "nonce":
            v["nonce"] = str(uuid4())
        v["mac"] = hmac.new(key, operator.canonical(v), hashlib.sha256).hexdigest()
        if self.mode == "mac":
            v["mac"] = "forged"
        if self.mode == "unsigned":
            v.pop("mac")
        self.data = operator.canonical(v) + b"\n"

    def recv(self, *a):
        data = self.data
        self.data = b""
        return data


with tempfile.TemporaryDirectory() as directory:
    p = Path(directory) / "key"
    p.write_bytes(key)
    p.chmod(0o600)
    os.environ["ZEBRA_ERPNEXT_ALLOCATOR_KEY_FILE"] = str(p)
    os.environ["ZEBRA_ERPNEXT_ALLOCATOR_SOCKET"] = "not-connected"
    c = client.PrivateWorkspaceClient()
    client.socket.socket = lambda *a, **k: Socket()
    for mode in ["valid", "nonce", "mac", "unsigned"]:
        Socket.mode = mode
        try:
            c.require(
                body["session_id"],
                SimpleNamespace(workspace_id=wid, quota_bytes=256 * 1024 * 1024),
                allow_allocate=False,
            )
        except ValueError as error:
            assert str(error) == (
                "workspace_capacity_exhausted"
                if mode == "valid"
                else "allocator receipt authentication failed"
            )
        else:
            raise AssertionError("refusal accepted")
print(
    "PASS signed refusal, nonce/MAC/unsigned denial, bounded input, "
    "redacted diagnostics and no quota bypass"
)
