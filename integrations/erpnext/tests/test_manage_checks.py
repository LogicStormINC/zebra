"""Run: python3 tests/test_manage_checks.py; no Redis, Frappe or Cloud writes."""

import json as json
import sys
import threading
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class Rejected(Exception):
    pass


class LockError(Exception):
    pass


lock = threading.Lock()


class Admission:
    def __enter__(self):
        if not lock.acquire(False):
            raise LockError()

    def __exit__(self, *args):
        lock.release()


frappe = types.ModuleType("frappe")
frappe.throw = lambda message, *args: (_ for _ in ()).throw(Rejected(message))
frappe.cache = types.SimpleNamespace(lock=lambda *args, **kwargs: Admission())
utils = types.ModuleType("frappe.utils")
utils.now_datetime = lambda: "now"
cloud = types.ModuleType("zebra_erpnext.cloud")
sys.modules.update(
    {
        "frappe": frappe,
        "frappe.utils": utils,
        "zebra_erpnext.cloud": cloud,
        "redis": types.ModuleType("redis"),
        "redis.exceptions": types.SimpleNamespace(LockError=LockError),
    }
)
chat = __import__("zebra_erpnext", fromlist=("chat",)).chat

persisted = dict(
    name="own",
    user="user",
    company="Company",
    title="old",
    status="idle",
    task_id=None,
    active_run_id="run",
    pending_command=None,
    client_surface_json="surface",
    presentation_json="new report and feedback",
    preferences_json="preserved",
)
stale = {**persisted, "presentation_json": "old snapshot"}
reads = []
writes = []
commits = []
requests = []
after_grant = None
header_status = "completed"


def owned(name, *, for_update=False, admission_lock=None):
    if admission_lock is not None:
        assert lock.locked()
    if for_update:
        assert lock.locked()
    reads.append(for_update)
    value = persisted if for_update else stale
    if value["user"] != "user":
        raise Rejected("Ownership changed")
    doc = types.SimpleNamespace(**value)
    doc.db_update = lambda: (_ for _ in ()).throw(AssertionError("Whole-document overwrite"))
    return doc


cloud.owned = owned


def set_value(table, name, fields, *args, **kwargs):
    assert lock.locked()
    if table == "Zebra Conversation":
        assert set(fields) in ({"title", "modified"}, {"status", "client_surface_json", "modified"})
        writes.append(dict(fields))
        persisted.update(fields)


def commit():
    assert lock.locked()
    commits.append(persisted.copy())


frappe.db = types.SimpleNamespace(set_value=set_value, commit=commit, delete=lambda *args: None)


def request(*args, **kwargs):
    requests.append(args)
    commit()
    if after_grant:
        after_grant()
    return {"current_turn_status": header_status}


cloud.request = request
assert chat.manage("own", title=" new title ")["title"] == "new title"
assert (
    reads == [False, True]
    and persisted["presentation_json"] == "new report and feedback"
    and persisted["preferences_json"] == "preserved"
)
assert len(commits) == 1 and commits[-1]["title"] == "new title"


def rejects(fn):
    try:
        fn()
    except Rejected:
        return
    raise AssertionError("Expected rejection")


for values in (
    {"status": "dispatching", "pending_command": None},
    {"status": "idle", "pending_command": "pinned"},
):
    persisted.update(values)
    before = (len(writes), len(requests), len(commits))
    rejects(lambda: chat.manage("own", delete=True))
    assert before == (len(writes), len(requests), len(commits))
persisted.update(status="running", pending_command=None, task_id="task")
header_status = "running"
before = len(writes)
rejects(lambda: chat.manage("own", delete=True))
assert len(writes) == before
header_status = "completed"


def pin_pending_after_grant():
    return persisted.update(pending_command="new pinned command")


after_grant = pin_pending_after_grant


rejects(lambda: chat.manage("own", delete=True))
assert len(writes) == before
persisted["pending_command"] = None


def change_owner_after_grant():
    return persisted.update(user="other")


after_grant = change_owner_after_grant


rejects(lambda: chat.manage("own", delete=True))
assert len(writes) == before
persisted["user"] = "user"
after_grant = None
assert chat.manage("own", delete=True)["deleted"]
assert (
    persisted["status"] == "deleted"
    and persisted["client_surface_json"] is None
    and persisted["presentation_json"] == "new report and feedback"
)
assert reads[-3:] == [False, True, True] and not lock.locked()
print(
    "PASS current locked reads, field-only management, preserved pres"
    "entation/preferences, in-lock commit, active/pending deletion de"
    "nial and post-grant ownership/state revalidation"
)
