"""python3 tests/test_reply_submission_checks.py; no DB/HTTP/model."""

import importlib
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class Rejected(Exception):
    def __init__(self, status):
        self.status_code = status
        self.reason = "denied"


class Unknown(Exception):
    pass


class Stop(Exception):
    pass


frappe = ModuleType("frappe")
frappe.db = SimpleNamespace(commit=lambda: None)
frappe.throw = lambda m: (_ for _ in ()).throw(Stop(m))
sys.modules["frappe"] = frappe
cloud = ModuleType("zebra_erpnext.cloud")
cloud.CloudRejectedError = Rejected
sys.modules["zebra_erpnext.cloud"] = cloud
m = importlib.import_module("zebra_erpnext.submission_recovery")


def fresh():
    d = SimpleNamespace(
        name="owned",
        task_id=None,
        active_run_id="run",
        request_id="request",
        request_options='{"reasoning_effort":"high"}',
        pending_command=None,
        pending_message="keep",
        stop_command=None,
        status="dispatching",
        prepared_request=None,
        prepared_revision=0,
    )
    d.db_update = lambda: None
    cloud.owned = lambda *a, **kw: d
    return d


lock = SimpleNamespace(owned=lambda: True)


def refused(*a, **kw):
    raise Rejected(403)


d = fresh()
cloud.request = refused
try:
    m.create_task(d, {"execute": False}, lock)
except Rejected:
    pass
assert (
    d.status == "rejected" and json.loads(d.request_options)["task_creation"]["state"] == "rejected"
)
assert d.pending_message == "keep"
result = m.stop_uncreated(d, lock)
assert result["status"] == "cancelled" and result["submission_cancelled"] is True
assert result.get("force_stop") is None, "never forge a native resource-reclamation proof"
# A previous unknown ACK cannot be erased by a later403.
d = fresh()
cloud.request = lambda *a, **kw: (_ for _ in ()).throw(Unknown())
try:
    m.create_task(d, {"execute": False}, lock)
except Unknown:
    pass
cloud.request = refused
try:
    m.create_task(d, {"execute": False}, lock)
except Rejected:
    pass
assert (
    d.status == "dispatching"
    and json.loads(d.request_options)["task_creation"]["state"] == "unknown"
)
cloud.request = lambda *a, **kw: {"status": "not_observed", "noncommit_proved": False}
assert m.stop_uncreated(d, lock)["submission_cancelled"] is False
assert d.status == "dispatching" and d.pending_message == "keep"
s = m.snapshot(d)
assert s["status"] != "idle" and s["run_state"]["phase"] == "reconciling"
# Observation can recover coordinates, but it can never submit a Run.
seen = []


def recorded(d, method, path, **kw):
    seen.append((method, path))
    return {
        "status": "recorded",
        "task_id": "11111111-1111-1111-1111-111111111111",
        "prepared_revision": 2,
    }


cloud.request = recorded
m.reconcile(d, lock)
assert d.task_id and d.prepared_request == "request" and d.prepared_revision == 2
assert seen == [("GET", "/task-admissions/receipt")]
# Late responses cannot overwrite a successor request.
d = fresh()


def successor(*a, **kw):
    d.active_run_id = "new"
    return {"task_id": "old"}


cloud.request = successor
try:
    m.create_task(d, {"execute": False}, lock)
except Stop:
    pass
else:
    raise AssertionError("late coordinates overwritten")
assert d.task_id is None
print(
    
        "PASS definite rejection, unknown retention, truthful pre-Task stop, GET-"
        "only recovery and successor guard"
    
)
