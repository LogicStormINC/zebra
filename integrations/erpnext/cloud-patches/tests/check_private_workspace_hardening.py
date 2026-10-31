"python3 cloud-patches/tests/check_private_workspace_hardening.py; stdlib, offline, no root/mount."

import hashlib
import hmac
import importlib.util
import io
import json
import os
import socket as socket
import stat as stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from uuid import uuid4

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "operator"))
allocator_impl = __import__("private_workspace_allocator")
proof_impl = __import__("private_workspace_native_proof")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


op = load("allocator_hardening", BASE / "operator/private_workspace_operator.py")


def refuses(call, errors=(ValueError, OSError, KeyError)):
    try:
        call()
    except errors:
        return
    raise AssertionError("expected fail closed")


def fixture(directory):
    root, state = Path(directory) / "root", Path(directory) / "state"
    root.mkdir()
    state.mkdir()
    with patch.object(allocator_impl, "trusted"):
        return op.Allocator(
            lambda s, w: ("a" * 64, "pending", time.time() + 60), root=root, state=state, floor=0
        )


with tempfile.TemporaryDirectory() as directory:
    allocator = fixture(directory)
    wid = str(uuid4())
    image = allocator.state / (wid + ".ext4")
    allocator.proof = lambda s, w: ("a" * 64, "pending", time.time() - 1)
    with patch.object(allocator_impl, "trusted"):
        refuses(
            lambda: allocator.ensure(
                dict(session_id=str(uuid4()), workspace_id=str(uuid4()), operation="ensure")
            )
        )
    assert not (allocator.state / "manifest.json").exists()
    # Existing crash-left fixed temp bytes are never overwritten/deleted.
    stale = allocator.state / "manifest.tmp"
    stale.write_bytes(b"unknown")
    allocator.save(dict(version=1, volumes={}, nonces={}))
    with patch.object(allocator_impl, "trusted"):
        assert stale.read_bytes() == b"unknown" and allocator.read()["version"] == 1
    image.touch()
    image.write_bytes(b"x")
    with patch.object(allocator_impl, "trusted"):
        allocator.capacity({})
        # One oversized orphan can exhaust bytes without exhausting 32 leaf slots.
        with image.open("r+b") as stream:
            stream.truncate(op.BYTE_LIMIT)
        refuses(lambda: allocator.capacity({}))
        image.unlink()
        image.symlink_to(stale)
        refuses(lambda: allocator.capacity({}))
        image.unlink()
        image.mkdir()
        refuses(lambda: allocator.capacity({}))
        image.rmdir()
        image.touch()
        # Sparse/orphan/reserved bytes are all charged against the disk floor, too.
        with patch.object(op.os, "statvfs", return_value=NS(f_bavail=op.SIZE, f_frsize=1)):
            refuses(lambda: allocator.capacity({}))
        image.unlink()
        with patch.object(op.os, "statvfs", return_value=NS(f_bavail=op.SIZE, f_frsize=1)):
            refuses(lambda: allocator.capacity({wid: dict(size=op.SIZE)}))
        refuses(lambda: allocator.capacity({wid: dict(size=op.SIZE + 1)}))
        bad = allocator.state / "unknown.ext4"
        bad.touch()
        refuses(lambda: allocator.capacity({}))
        bad.unlink()
    # Lock acquisition and child commands share the same absolute remaining budget.
    token = op.DEADLINE.set(time.monotonic() + 0.04)
    allocator.thread_lock.acquire()
    started = time.monotonic()
    try:
        refuses(lambda: allocator.locked().__enter__(), (TimeoutError,))
    finally:
        allocator.thread_lock.release()
        op.DEADLINE.reset(token)
    assert time.monotonic() - started < 1
    token = op.DEADLINE.set(time.monotonic() + 0.04)
    started = time.monotonic()
    try:
        refuses(
            lambda: op.run(sys.executable, "-c", "import time; time.sleep(2)"),
            (subprocess.TimeoutExpired,),
        )
    finally:
        op.DEADLINE.reset(token)
    assert time.monotonic() - started < 1

with tempfile.TemporaryDirectory() as directory:
    allocator = fixture(directory)
    request = dict(
        session_id=str(uuid4()),
        workspace_id=str(uuid4()),
        request_id=str(uuid4()),
        operation="ensure",
    )
    calls = []

    def command(*args):
        calls.append(args)
        if args[0] == "blkid":
            return str(uuid4())
        if args[0] == "mount":
            raise TimeoutError("lost mount result")
        return ""

    with patch.object(allocator_impl, "trusted"), patch.object(allocator_impl, "run", command):
        refuses(lambda: allocator.ensure(request))
        assert allocator.read()["volumes"][request["workspace_id"]]["phase"] == "formatted"
        refuses(lambda: allocator.ensure(request))
        refuses(allocator.restore)
    assert len([c for c in calls if c[0] == "mkfs.ext4"]) == 1
    assert not (allocator.root / ".identities").exists()

config = dict(
    helper_image="native@sha256:" + "a" * 64,
    helper_network="erpnext-private-proof",
    helper_hostname="erpnext.zebra.local",
    readonly_dsn="secret-dsn",
    host_tool_shared_secret="secret-key",
)
proof = op.NativeProof(config)
sid, wid = str(uuid4()), str(uuid4())
captured = []


def container(argv, **kw):
    captured.append((argv, kw))
    request = json.loads(kw["input"])
    return op.canonical(
        dict(
            identity="a" * 64,
            state="pending",
            expires_at=2000000000.0,
            **{k: request[k] for k in ("session_id", "workspace_id", "nonce")},
        )
    )


with (
    patch.object(op.subprocess, "check_output", side_effect=container),
    patch.object(op.subprocess, "run", return_value=NS(returncode=0)) as cleanup,
):
    assert proof(sid, wid) == ("a" * 64, "pending", 2000000000.0)
    argv, kw = captured[0]
    assert "secret-dsn" not in repr(argv) and "secret-key" not in repr(argv)
    assert all(
        word not in argv for word in ("--volume", "--mount", "--privileged", "--network=host")
    )
    assert "--pull=never" in argv
    assert argv[argv.index("--network") + 1] == "erpnext-private-proof"
    assert argv.count("--env") == 2
    assert "ZEBRA_FULL_QA=false" in argv
    assert (
        argv[argv.index("--env") + 1] == "ZEBRA_HOST_TOOL_SSRF_ALLOW_HOSTNAMES=erpnext.zebra.local"
    )
    assert set(json.loads(kw["input"])) == {
        "readonly_dsn",
        "shared_secret",
        "ca_pem",
        "session_id",
        "workspace_id",
        "nonce",
    }
    assert (
        json.loads(kw["input"])["session_id"] == sid
        and json.loads(kw["input"])["workspace_id"] == wid
    )
    assert json.loads(kw["input"])["nonce"] == argv[argv.index("--name") + 1].removeprefix(
        "erp-private-proof-"
    )
    assert argv[argv.index("--user") + 1] == "65532:65532"
    assert kw["timeout"] <= 7 and cleanup.call_args.kwargs["timeout"] == 5
    assert cleanup.call_args.args[0][-1] == argv[argv.index("--name") + 1]
with (
    patch.object(
        op.subprocess, "check_output", side_effect=subprocess.TimeoutExpired("docker", 0.01)
    ),
    patch.object(op.subprocess, "run", return_value=NS(returncode=0)) as cleanup,
):
    refuses(lambda: proof(sid, wid), (subprocess.TimeoutExpired,))
    assert cleanup.called
with (
    patch.object(op.subprocess, "check_output", return_value=b"{}"),
    patch.object(op.subprocess, "run", return_value=NS(returncode=0)),
):
    refuses(lambda: proof(sid, wid))
local = op.NativeProof(dict(config, helper_image="sha256:" + "b" * 64))
assert local.image == "sha256:" + "b" * 64
with (
    patch.object(op.subprocess, "check_output", return_value=b"{}") as launch,
    patch.object(op.subprocess, "run", return_value=NS(returncode=1)),
):
    refuses(lambda: local(sid, wid))
    assert local.failed_cleanup
    refuses(lambda: local(sid, wid))
    assert launch.call_count == 1
with patch.object(op.subprocess, "check_output", return_value="erp-private-proof-stale\n"):
    refuses(proof.require_clean)
refuses(lambda: op.NativeProof(dict(config, helper_image="native:latest")))
refuses(lambda: op.NativeProof(dict(config, helper_network="host")))
refuses(lambda: op.NativeProof({k: v for k, v in config.items() if k != "helper_hostname"}))
for hostname in (
    None,
    1,
    "",
    "localhost",
    "a.localhost",
    "localhost.localdomain",
    "127.0.0.1",
    "127.1",
    "2130706433",
    "0x7f000001",
    "127.0x1",
    "0x7f.0x1",
    "0177.0x1",
    "a.123",
    "::1",
    "[::1]",
    "https://erpnext.zebra.local",
    "erpnext.zebra.local:443",
    "ERPNext.zebra.local",
    " erpnext.zebra.local",
    "erpnext.zebra.local\n",
    "a.local,b.local",
    "*.zebra.local",
    "a..local",
    "-a.local",
    "a-.local",
    "a_.local",
    "a.local.",
    "a" * 64 + ".local",
    ".".join(["a" * 63] * 4),
):
    refuses(lambda *, hostname=hostname: op.NativeProof(dict(config, helper_hostname=hostname)))
for hostname in ("a.b", "a" * 63 + "." + "b" * 63 + "." + "c" * 63 + "." + "d" * 61):
    assert op.NativeProof(dict(config, helper_hostname=hostname)).hostname == hostname
# Root config alone controls the sole explicit env even if the parent process has a broad value.
with (
    patch.dict(os.environ, {"ZEBRA_HOST_TOOL_SSRF_ALLOW_HOSTNAMES": "*"}),
    patch.object(op.subprocess, "check_output", side_effect=container),
    patch.object(op.subprocess, "run", return_value=NS(returncode=0)),
):
    op.NativeProof(dict(config, helper_hostname="authority-qa-fc59cd41.local"))(sid, wid)
    argv, kw = captured[-1]
    assert argv.count("--env") == 2
    assert "ZEBRA_FULL_QA=false" in argv
    assert (
        argv[argv.index("--env") + 1]
        == "ZEBRA_HOST_TOOL_SSRF_ALLOW_HOSTNAMES=authority-qa-fc59cd41.local"
    )
    assert "*" not in repr(argv)
with (
    patch.object(
        op.subprocess,
        "check_output",
        side_effect=lambda *args, **kw: op.canonical(
            dict(json.loads(container(*args, **kw)), nonce=str(uuid4()))
        ),
    ),
    patch.object(op.subprocess, "run", return_value=NS(returncode=0)),
):
    refuses(lambda: proof(sid, wid))

# Exercise actual Worker receipt parser+mount identity check, with only kernel/socket seams mocked.
quota = ModuleType("agent_runtime.workspace_quota")
quota.require_workspace_quota = lambda *a, **kw: NS(capacity_bytes=100, filesystem="ext4")
with patch.dict(sys.modules, {"agent_runtime.workspace_quota": quota}):
    worker = load(
        "worker_private_hardening",
        BASE / "overrides/packages/agent-runtime/src/agent_runtime/erp_private_workspace.py",
    )
client = object.__new__(worker.PrivateWorkspaceClient)
client.key = b"x" * 32
client.socket = "/fixed"
fsuuid = str(uuid4())
identity = dict(workspace_id=wid, filesystem_uuid=fsuuid, filesystem_id=123)
receipt = dict(
    identity, path=str(worker.ROOT / wid), device=42, capacity_bytes=100, maximum_bytes=256
)


class Socket:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def settimeout(self, *args):
        pass

    def connect(self, path):
        assert path == "/fixed"

    def sendall(self, data):
        self.request = json.loads(data)["body"]
        self.sent = False

    def recv(self, size):
        if self.sent:
            return b""
        self.sent = True
        result = dict(ok=True, receipt=receipt, nonce=self.request["nonce"])
        result["mac"] = hmac.new(client.key, worker.canonical(result), hashlib.sha256).hexdigest()
        return worker.canonical(result) + b"\n"


with (
    patch.object(worker.socket, "socket", return_value=Socket()),
    patch.object(worker.Path, "is_symlink", return_value=False),
    patch.object(worker.Path, "resolve", lambda self, **kw: self),
    patch.object(worker.Path, "stat", return_value=NS(st_dev=42)),
    patch.object(worker.os, "statvfs", return_value=NS(f_fsid=123)),
    patch.object(worker, "persistent_identity", return_value=identity),
):
    instance = NS(workspace_id=wid, quota_bytes=256)
    assert client.require(sid, instance, allow_allocate=False) == worker.ROOT / wid
    receipt["filesystem_uuid"] = str(uuid4())
    refuses(lambda: client.require(sid, instance, allow_allocate=False))
    receipt["filesystem_uuid"] = fsuuid
    with patch.object(worker.os, "statvfs", return_value=NS(f_fsid=999)):
        refuses(lambda: client.require(sid, instance, allow_allocate=False))

# Real immutable metadata parsing (only test-host ownership is substituted).
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory).resolve()
    identities = root / ".identities"
    identities.mkdir()
    path = identities / (wid + ".json")
    path.write_text(json.dumps(identity))
    real_lstat, real_fstat = worker.Path.lstat, worker.os.fstat

    def root_lstat(path):
        info = real_lstat(path)
        return NS(st_uid=0, st_mode=info.st_mode & ~0o022)

    def root_fstat(fd):
        info = real_fstat(fd)
        return NS(
            st_uid=0, st_mode=info.st_mode & ~0o022, st_nlink=info.st_nlink, st_size=info.st_size
        )

    with (
        patch.object(worker, "ROOT", root),
        patch.object(worker.Path, "lstat", root_lstat),
        patch.object(worker.os, "fstat", root_fstat),
    ):
        assert worker.persistent_identity(root / wid) == identity
        invalid = dict(identity, filesystem_uuid="not-a-uuid")
        path.write_text(json.dumps(invalid))
        refuses(lambda: worker.persistent_identity(root / wid))
        path.unlink()
        path.symlink_to(root / "foreign")
        refuses(lambda: worker.persistent_identity(root / wid))

print(
    "PASS offline byte/debt budgets, stale-temp preservation, phase c"
    "rash/no-reformat, shared deadlines, helper confinement/nonce/cle"
    "anup, Worker persistent UUID+kernel identity"
)

# A global-deadline alarm may have fired before finally; never start post-budget cleanup.
late = op.NativeProof(config)
with (
    patch.object(proof_impl, "remaining", side_effect=[6, TimeoutError("expired")]),
    patch.object(op.subprocess, "check_output", side_effect=container),
    patch.object(op.subprocess, "run") as cleanup,
):
    refuses(lambda: late(sid, wid))
    assert late.failed_cleanup and not cleanup.called
short = op.NativeProof(config)
with (
    patch.object(proof_impl, "remaining", return_value=0.5),
    patch.object(op.subprocess, "check_output") as launch,
    patch.object(op.subprocess, "run") as cleanup,
):
    refuses(lambda: short(sid, wid))
    assert not launch.called and not cleanup.called and not short.failed_cleanup

# Capture the actual serial handler; no socket/root/network or real alarm needed.

clock = [100.0]
timers = []


def timer(kind, seconds):
    timers.append(seconds)


class BudgetServer:
    def __init__(self, address, handler):
        self.handler = handler

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def serve_forever(self):
        for used in (19, 21):
            clock[0] = 100
            handler = object.__new__(self.handler)
            timeouts = []
            handler.request = NS(
                settimeout=timeouts.append,
                getsockopt=lambda *a: op.struct.pack("3i", 1, 65532, 65532),
            )
            handler.rfile = io.BytesIO(b"{}\n")

            def ensure(request, *, used=used):
                clock[0] = 100 + used
                return {}

            allocator.ensure = ensure

            def write(data, *, timeouts=timeouts, used=used):
                assert used == 19
                assert op.DEADLINE.get() == 120 and timers[-1] == 20
                assert timeouts[-1] == 1
                clock[0] = 120
                raise TimeoutError("response consumed remaining budget")

            handler.wfile = NS(write=Mock(side_effect=write))
            handler.handle()
            assert handler.wfile.write.call_count == (1 if used == 19 else 0)
            assert timers[-1] == 0 and op.DEADLINE.get() is None


allocator = NS(worker_uid=65532, authenticate=lambda *a: dict(nonce="n"))
with (
    tempfile.TemporaryDirectory() as directory,
    patch.object(op, "trusted"),
    patch.object(op.socketserver, "UnixStreamServer", BudgetServer),
    patch.object(op.signal, "signal"),
    patch.object(op.signal, "setitimer", timer),
    patch.object(op.time, "monotonic", lambda: clock[0]),
    patch.object(op.os, "chown"),
    patch.object(op.os, "chmod"),
    patch.object(op.socket, "SO_PEERCRED", 17, create=True),
):
    op.serve(allocator, Path(directory) / "socket", b"x" * 32)
print(
    "PASS absolute handler deadline includes response and reserved he"
    "lper cleanup; expired cleanup latches without post-deadline spaw"
    "n"
)

# Deterministic deadline replay: observed die-to-destroy interval 3.797s (not rm RPC measurement).
assert op.REQUEST_SECONDS == 20
for available, launch_duration, cleanup_duration, fails in (
    (20, 7, 3.797, False),
    (6, 1, 3.797, False),
    (5.5, 0.5, 3.797, False),
    (6, 1, 5.1, True),
):
    clock = [100.0]
    token = op.DEADLINE.set(clock[0] + available)
    bounded = op.NativeProof(config)

    def launch_owned(
        argv, *, available=available, clock=clock, launch_duration=launch_duration, **kw
    ):
        assert kw["timeout"] == min(7, available - 5)
        assert kw["timeout"] + 5 <= available
        clock[0] += launch_duration
        return container(argv, **kw)

    def remove_owned(
        argv, *, available=available, cleanup_duration=cleanup_duration, clock=clock, **kw
    ):
        assert argv == [
            "docker",
            "rm",
            "--force",
            captured[-1][0][captured[-1][0].index("--name") + 1],
        ]
        assert kw["timeout"] == min(5, 100 + available - clock[0])
        clock[0] += min(cleanup_duration, kw["timeout"])
        if cleanup_duration > kw["timeout"]:
            raise subprocess.TimeoutExpired(argv, kw["timeout"])
        return NS(returncode=0)

    try:
        with (
            patch.object(op.time, "monotonic", lambda *, clock=clock: clock[0]),
            patch.object(op.subprocess, "check_output", side_effect=launch_owned) as launch,
            patch.object(op.subprocess, "run", side_effect=remove_owned) as cleanup,
        ):
            if fails:
                refuses(lambda *, bounded=bounded: bounded(sid, wid))
                assert bounded.failed_cleanup
                refuses(lambda *, bounded=bounded: bounded(sid, wid))
                assert launch.call_count == cleanup.call_count == 1
            else:
                assert bounded(sid, wid) == ("a" * 64, "pending", 2000000000.0)
                assert not bounded.failed_cleanup
            assert clock[0] <= 100 + available <= 120
    finally:
        op.DEADLINE.reset(token)
for available in (5, 4.999):
    bounded = op.NativeProof(config)
    with (
        patch.object(proof_impl, "remaining", return_value=available),
        patch.object(op.subprocess, "check_output") as launch,
        patch.object(op.subprocess, "run") as cleanup,
    ):
        refuses(lambda *, bounded=bounded: bounded(sid, wid), (TimeoutError,))
        assert not launch.called and not cleanup.called and not bounded.failed_cleanup
print(
    "PASS measured slow cleanup, near-deadline launch reservation, st"
    "icky timeout, exact owned removal, original 20s bound"
)
