"""python3 cloud-patches/tests/check_private_workspace.py (no mount/root/network)."""

import ast
import hashlib
import hmac
import importlib.util
import json as json
import os as os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "operator"))
allocator_impl = __import__("private_workspace_allocator")


spec = importlib.util.spec_from_file_location(
    "operator_impl", ROOT / "operator/private_workspace_operator.py"
)
op = importlib.util.module_from_spec(spec)
spec.loader.exec_module(op)


def refuses(call):
    try:
        call()
    except (ValueError, OSError, KeyError):
        return
    raise AssertionError("expected fail closed")


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory) / "root"
    state = Path(directory) / "state"
    root.mkdir()
    state.mkdir()
    calls = []
    identity = "a" * 64
    sid, wid = str(uuid4()), str(uuid4())
    with patch.object(allocator_impl, "trusted"):
        allocator = op.Allocator(
            lambda s, w: (identity, "pending", time.time() + 60), root=root, state=state, floor=0
        )
    request = dict(
        session_id=sid,
        workspace_id=wid,
        request_id=str(uuid4()),
        nonce=str(uuid4()),
        timestamp=int(time.time()),
        operation="ensure",
    )
    key = b"x" * 32
    packet = dict(
        body=request, mac=hmac.new(key, op.canonical(request), hashlib.sha256).hexdigest()
    )
    with patch.object(allocator_impl, "trusted"):
        assert allocator.authenticate(packet, key, 65532) == request
        refuses(lambda: allocator.authenticate(packet, key, 65532))
        refuses(lambda: allocator.authenticate(packet, key, 0))
        bad = dict(packet, mac="0" * 64)
        refuses(lambda: allocator.authenticate(bad, key, 65532))
        bad = dict(request, path="/tmp/foreign")
        refuses(lambda: allocator.authenticate(dict(body=bad, mac="0" * 64), key, 65532))
    assert not list(root.iterdir()) and not list(state.glob("*.ext4"))

    def command(*args):
        calls.append(args)
        if args[0] == "mount":
            (Path(args[-1]) / "lost+found").mkdir()
        if args[0] == "blkid":
            return "12345678-1234-1234-1234-123456789abc"
        return ""

    def receipt(w, record):
        assert record["phase"] == "ready"
        return {
            "workspace_id": w,
            "filesystem_uuid": record["filesystem_uuid"],
            "identity": record["identity"],
        }

    # Simulate kernel calls only; exercise actual reservations/journal/auth/concurrency.
    with (
        patch.object(allocator_impl, "run", command),
        patch.object(op.os, "posix_fallocate", create=True),
        patch.object(op.os, "chown"),
        patch.object(allocator, "verify", receipt),
        patch.object(allocator_impl, "trusted"),
    ):
        with ThreadPoolExecutor(max_workers=8) as pool:
            receipts = list(pool.map(lambda _: allocator.ensure(request), range(8)))
        assert all(value == receipts[0] for value in receipts)
        assert len([call for call in calls if call[0] == "mkfs.ext4"]) == 1
        assert len(list(state.glob("*.ext4"))) == 1
        allocator.proof = lambda s, w: ("b" * 64, "pending", time.time() + 60)
        refuses(lambda: allocator.ensure(request))
        allocator.proof = lambda s, w: (identity, "pending", time.time() + 60)
        verify_unknown = dict(request, workspace_id=str(uuid4()), operation="verify")
        refuses(lambda: allocator.ensure(verify_unknown))
        assert len(list(state.glob("*.ext4"))) == 1
        foreign = dict(request, workspace_id=str(uuid4()))
        (root / foreign["workspace_id"]).symlink_to(root / wid)
        refuses(lambda: allocator.ensure(foreign))
        with patch.object(allocator_impl, "LIMIT", 1):
            refuses(lambda: allocator.ensure(dict(request, workspace_id=str(uuid4()))))
        # A partial format never gets formatted a second time, including restart.
        journal = allocator.read()
        journal["volumes"][str(uuid4())] = dict(phase="reserved", size=op.SIZE, identity=identity)
        allocator.save(journal)
        with patch.object(op.os.path, "ismount", return_value=True):
            refuses(allocator.restore)
        assert len([call for call in calls if call[0] == "mkfs.ext4"]) == 1

# Strict root ownership rejects an actual symlink before any mutation.
with tempfile.TemporaryDirectory() as directory:
    link = Path(directory) / "link"
    link.symlink_to("/")
    refuses(lambda: op.trusted(link))

# Source-level invariant: allocator precedes native provision_start/reset, and
# both fresh and continuation paths verify before returning materialized roots.
source = (
    ROOT / "overrides/packages/agent-runtime/src/agent_runtime/workspace_runtime_resolver.py"
).read_text()
source = ast.unparse(ast.parse(source))
assert source.index("self._private_guard(session_id, existing") < source.index(
    "self._provisioner.provision_existing(workspace_id)"
)
assert source.count("self._private_guard(session_id, instance, allow_allocate=False)") == 3
source = (ROOT / "overrides/apps/worker/src/zebra_agent_worker/execution_attempt.py").read_text()
source = ast.unparse(ast.parse(source))
assert (
    source.index("require_early_authority(fresh.probe(datetime.now(started_at.tzinfo)))")
    < source.index("self._workspace_resolver.resolve(claimed.recovery.workspace.workspace_root")
    < source.index("inputs = prepare_execution_inputs(")
)
print(
    "PASS private allocator authentication/replay/reservation/concurr"
    "ency/lost-ACK/foreign/symlink/budget/crash and hook order"
)
