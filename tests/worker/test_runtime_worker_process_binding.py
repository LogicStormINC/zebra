import base64
import hashlib
import hmac
import io
import json
from contextlib import redirect_stdout
from uuid import UUID

from zebra_agent_worker.runtime_instance_binding import VERSION, emit_runtime_instance_binding


def test_runtime_process_binding_signs_exact_actual_observer_identity() -> None:
    instance = "a0000000-0000-4000-8000-000000000001"
    process = UUID("b0000000-0000-4000-8000-000000000001")
    output = io.StringIO()
    with redirect_stdout(output):
        emit_runtime_instance_binding(instance, "namespace", process, b"a" * 32)
    envelope = json.loads(output.getvalue())
    assert envelope["contractVersion"] == VERSION
    encoded = base64.urlsafe_b64decode(envelope["payload"] + "=" * (-len(envelope["payload"]) % 4))
    result = json.loads(encoded)
    signature = envelope["signature"]
    assert result == {
        "contractVersion": VERSION,
        "instanceId": instance,
        "namespaceId": "namespace",
        "processId": str(process),
    }
    encoded = json.dumps(result, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    assert (
        signature
        == "hmac-sha256:"
        + hmac.new(b"a" * 32, VERSION.encode() + b"\n" + encoded, hashlib.sha256).hexdigest()
    )
    assert "key" not in output.getvalue() and "rtbind_" not in output.getvalue()
    result["processId"] = str(UUID(int=1))
    tampered = json.dumps(result, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    assert (
        signature
        != "hmac-sha256:"
        + hmac.new(b"a" * 32, VERSION.encode() + b"\n" + tampered, hashlib.sha256).hexdigest()
    )
