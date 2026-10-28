"""Signed startup artifact, never a compatibility or execution authorization."""

import base64
import hashlib
import hmac
import json
from uuid import UUID

VERSION = "runtime-worker-process/1"


def emit_runtime_instance_binding(instance: str, namespace: str, process: UUID, key: bytes) -> None:
    if str(UUID(instance)) != instance or not namespace or len(namespace) > 256 or len(key) != 32:
        raise ValueError("INVALID_RUNTIME_INSTANCE_BINDING")
    body = {
        "contractVersion": VERSION,
        "instanceId": instance,
        "namespaceId": namespace,
        "processId": str(process),
    }
    encoded = json.dumps(body, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    signature = hmac.new(key, VERSION.encode() + b"\n" + encoded, hashlib.sha256).hexdigest()
    print(
        json.dumps(
            {
                "contractVersion": VERSION,
                "payload": base64.urlsafe_b64encode(encoded).decode().rstrip("="),
                "signature": "hmac-sha256:" + signature,
            },
            sort_keys=True,
        ),
        flush=True,
    )
