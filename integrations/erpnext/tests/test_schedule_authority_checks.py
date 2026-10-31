"""python3 tests/test_schedule_authority_checks.py; no DB/model/search calls."""

import hashlib
import hmac
import json
import sys
import types
from pathlib import Path
from uuid import uuid4

frappe = types.ModuleType("frappe")
cloud = types.ModuleType("zebra_erpnext.cloud")
sys.modules.update({"frappe": frappe, "zebra_erpnext.cloud": cloud})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
verified_request = __import__(
    "zebra_erpnext.schedule_authority", fromlist=("verified_request",)
).verified_request

secret = "local-test-only-not-a-service-credential"
now = 1793190000
body = {
    "audience": "zebra",
    "threadId": str(uuid4()),
    "runId": str(uuid4()),
    "scopes": ["agent.run", "erpnext.read"],
    "principal": {"userId": "owner", "workspaceId": "private"},
    "resourceRefs": [
        {"type": "company", "id": "Own Company"},
        {"type": "schedule_request", "id": "owned-source"},
    ],
}


def sign(value):
    digest = hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    headers = {
        "X-Zebra-Workload-Identity": "erpnext-scheduler-full",
        "X-Zebra-Workload-Timestamp": str(now),
        "X-Zebra-Workload-Nonce": value["runId"],
    }
    headers["X-Zebra-Workload-Signature"] = hmac.new(
        secret.encode(), f"{now}\n{value['runId']}\n{digest}".encode(), hashlib.sha256
    ).hexdigest()
    return headers


settings = {"schedule_workload_secret": secret}
headers = sign(body)
assert verified_request(body, headers, settings, now) == {
    "company": "Own Company",
    "schedule_request": "owned-source",
}
for changed, head, moment in [
    ({**body, "audience": "other"}, headers, now),
    (body, {**headers, "X-Zebra-Workload-Signature": "0" * 64}, now),
    (body, {**headers, "X-Zebra-Workload-Identity": "browser"}, now),
    (body, headers, now + 31),
    ({**body, "principal": {"userId": "other", "workspaceId": "private"}}, headers, now),
    (
        {**body, "resourceRefs": body["resourceRefs"] + [{"type": "company", "id": "foreign"}]},
        headers,
        now,
    ),
]:
    try:
        verified_request(changed, head, settings, moment)
    except (ValueError, TypeError):
        pass
    else:
        raise AssertionError("tampered/expired authority accepted")
bad = {
    **body,
    "resourceRefs": [
        {"type": "company", "id": "Own Company"},
        {"type": "company", "id": "foreign"},
    ],
}
try:
    verified_request(bad, sign(bad), settings, now)
except ValueError:
    pass
else:
    raise AssertionError("ambiguous resource scope accepted")
print("scheduler signature, timestamp, nonce and exact resource boundaries: passed")
