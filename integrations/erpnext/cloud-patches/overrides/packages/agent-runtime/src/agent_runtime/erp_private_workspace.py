"""Authenticated Worker-only client and independent local mount verification."""

import hashlib
import hmac
import json
import os
import socket
import stat
import time
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from agent_runtime.workspace_quota import require_workspace_quota

ROOT = Path("/var/lib/zebra/erpnext-private-workspaces")


def persistent_identity(path):
    directory = ROOT / ".identities"
    for parent in [*reversed(directory.parents), directory]:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("unsafe persistent filesystem identity directory")
    descriptor = os.open(directory / (path.name + ".json"), os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0
            or info.st_mode & 0o022
            or info.st_nlink != 1
            or info.st_size > 1024
        ):
            raise ValueError("unsafe persistent filesystem identity")
        value = json.loads(stream.read(1025))
    if (
        set(value) != {"workspace_id", "filesystem_uuid", "filesystem_id"}
        or value["workspace_id"] != path.name
        or str(UUID(value["filesystem_uuid"])) != value["filesystem_uuid"]
        or type(value["filesystem_id"]) is not int
    ):
        raise ValueError("invalid persistent filesystem identity")
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def private_enabled(namespace):
    value = os.environ.get("ZEBRA_ERPNEXT_PRIVATE_WORKSPACES", "disabled")
    if value not in {"enabled", "disabled"}:
        raise ValueError("invalid private workspace opt-in")
    if value == "enabled" and (
        namespace != "erpnext"
        or os.environ.get("ZEBRA_ERPNEXT_FRESH_AUTHORITY") != "enabled"
        or os.environ.get("ZEBRA_ERPNEXT_WORKSPACE_CONTAINMENT") != "enabled"
        or os.environ.get("ZEBRA_WORKSPACE_VOLUME_ROOT") != str(ROOT)
        or os.environ.get("ZEBRA_WORKSPACE_VOLUME_LAYOUT") != "per-workspace"
    ):
        raise ValueError("private workspace activation requires fixed ERP isolation wiring")
    return value == "enabled"


class PrivateWorkspaceClient:
    def __init__(self):
        self.socket = os.environ["ZEBRA_ERPNEXT_ALLOCATOR_SOCKET"]
        key_path = Path(os.environ["ZEBRA_ERPNEXT_ALLOCATOR_KEY_FILE"])
        info = key_path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022:
            raise ValueError("unsafe allocator credential")
        self.key = key_path.read_bytes()
        if len(self.key) < 32:
            raise ValueError("insufficient allocator credential")

    def require(self, session_id, instance, *, allow_allocate):
        wid = str(instance.workspace_id)
        path = ROOT / wid
        body = dict(
            session_id=str(session_id),
            workspace_id=wid,
            request_id=str(uuid5(UUID(wid), "erpnext-private-workspace-v1")),
            nonce=str(uuid4()),
            timestamp=int(time.time()),
            operation="ensure" if allow_allocate else "verify",
        )
        packet = dict(
            body=body, mac=hmac.new(self.key, canonical(body), hashlib.sha256).hexdigest()
        )
        deadline = time.monotonic() + 30
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(30)
            client.connect(self.socket)
            client.settimeout(max(0.001, deadline - time.monotonic()))
            client.sendall(canonical(packet) + b"\n")
            data = b""
            while not data.endswith(b"\n") and len(data) <= 4096:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError("allocator response deadline exceeded")
                client.settimeout(left)
                chunk = client.recv(4097 - len(data))
                if not chunk:
                    break
                data += chunk
        if len(data) > 4096 or not data.endswith(b"\n"):
            raise ValueError("invalid allocator response")
        result = json.loads(data)
        mac = result.pop("mac", "")
        if (
            result.get("ok") is not True
            or result.get("nonce") != body["nonce"]
            or not hmac.compare_digest(
                hmac.new(self.key, canonical(result), hashlib.sha256).hexdigest(), mac
            )
        ):
            raise ValueError("allocator receipt authentication failed")
        receipt = result["receipt"]
        if (
            receipt["workspace_id"] != wid
            or receipt["path"] != str(path)
            or receipt["maximum_bytes"] != instance.quota_bytes
            or path.is_symlink()
            or path.resolve(strict=True) != path
        ):
            raise ValueError("allocator receipt facts disagree")
        quota = require_workspace_quota(path, maximum_bytes=instance.quota_bytes)
        identity = persistent_identity(path)
        # Device identity is meaningful across host/Worker mount namespaces; inode
        # and mount IDs are not. A parent-backed directory cannot pass this check.
        if (
            path.stat().st_dev != receipt["device"]
            or quota.capacity_bytes != receipt["capacity_bytes"]
            or quota.filesystem != "ext4"
            or os.statvfs(path).f_fsid != identity["filesystem_id"]
            or any(receipt.get(key) != value for key, value in identity.items())
        ):
            raise ValueError("Worker mount propagation or filesystem identity mismatch")
        return path
