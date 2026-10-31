"""Run python3 tests/check_fresh_refusal_bff.py; actual BFF/client code, IO doubles.

No Frappe DB, Redis or native HTTP is claimed by this deterministic state check.
"""

import json
import sys
from pathlib import Path
from threading import Lock
from types import ModuleType
from types import SimpleNamespace as Simple
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


class Rejected(Exception):
    pass


class LockError(Exception):
    pass


class CloudRejected(Rejected):
    def __init__(self, status, reason):
        self.status_code, self.reason = status, reason


class Mutex:
    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        if not mutex.acquire(False):
            raise LockError()
        return self

    def __exit__(self, *a):
        mutex.release()

    def owned(self):
        return True


mutex = Lock()
committed = []
frappe = ModuleType("frappe")
frappe.throw = lambda message, *args: (_ for _ in ()).throw(Rejected(message))
frappe.parse_json = json.loads
frappe.cache = Simple(lock=Mutex)
frappe.db = Simple(commit=lambda: committed.append(json.loads(doc.request_options or "{}")))
frappe.local = Simple(request=Simple(headers={"Origin": "https://erp.example.test"}))
frappe.whitelist = lambda **kw: lambda fn: fn
utils = ModuleType("frappe.utils")
utils.now_datetime = lambda: None
package = ModuleType("zebra_erpnext")
package.__path__ = [str(ROOT / "host-overrides/zebra_erpnext")]
cloud = ModuleType("zebra_erpnext.cloud")
cloud.CloudRejectedError = CloudRejected
cloud.owned = lambda name, **kw: doc
cloud.require_admission_open = lambda *a: None
cloud.config = lambda: {
    "origin": "https://erp.example.test",
    "frontend_profile": {"actions": [], "digest": "a" * 64, "revision": 1, "action_digests": {}},
}
redis = ModuleType("redis")
exceptions = ModuleType("redis.exceptions")
exceptions.LockError = LockError
sys.modules.update(
    {
        "frappe": frappe,
        "frappe.utils": utils,
        "redis": redis,
        "redis.exceptions": exceptions,
        "zebra_erpnext": package,
        "zebra_erpnext.cloud": cloud,
    }
)
chat = __import__("zebra_erpnext", fromlist=("chat",)).chat
client = __import__("zebra_erpnext", fromlist=("client",)).client
history = __import__("zebra_erpnext", fromlist=("history",)).history


class Doc:
    def __init__(self):
        self.name = "owned"
        self.task_id = str(uuid4())
        self.active_run_id = str(uuid4())
        self.user = "owner"
        self.status = "running"
        self.request_id = str(uuid4())
        self.pending_message = "original private message"
        self.request_options = json.dumps(
            {
                "model_profile": chat.MODEL_OPTIONS[0]["value"],
                "reasoning_effort": "high",
                "context": {"doctype": "Sales Order", "name": "SO-1"},
            }
        )
        self.pending_command = None
        self.stop_command = None
        self.client_surface_json = None

    def db_update(self):
        pass


def reset(mode="allow"):
    global doc, predecessor, eid, calls, accepted, behavior, first, revision
    doc = Doc()
    predecessor = doc.active_run_id
    eid = str(uuid4())
    calls = []
    accepted = {}
    behavior = mode
    first = True
    revision = 3
    return str(uuid4())


def request(current, method, path, **kwargs):
    global first
    op = json.loads(doc.request_options)["fresh_retry"]
    assert op["phase"] in {"preparing", "dispatching"} and committed
    calls.append((method, path, kwargs))
    if method == "GET":
        if behavior == "grant_denied":
            raise CloudRejected(403, "host_authorization_required")
        return {
            "status": "ready",
            "active_segment_sequence": revision,
            "command_outcome": {
                "code": "erp_fresh_authority_refused",
                "run_id": predecessor,
                "accepted_event_id": eid,
                "retry_eligible": True,
            },
        }
    if path.endswith("/release"):
        if behavior == "unknown_release" and first:
            first = False
            raise Rejected("unknown release")
        return {}
    if path.endswith("/client-surface"):
        assert json.loads(doc.client_surface_json)["opening_run"] == op["run_id"]
        if behavior == "unknown_open" and first:
            first = False
            raise Rejected("unknown open")
        return dict(
            client_session_id=str(uuid4()),
            session_credential="test-only",
            controller_fence_token="fence",
            binding_id="binding",
            binding_digest="b" * 64,
        )
    assert path == "/agui/commands" and op["phase"] == "dispatching"
    assert kwargs["body"] == json.loads(doc.pending_command)
    assert (
        kwargs["body"]["input"]["messages"] == []
        and doc.pending_message == "original private message"
    )
    assert kwargs["key"] == "erpnext-fresh-" + op["operation_id"]
    if behavior == "known_reject":
        raise CloudRejected(409, "revision_conflict")
    if behavior == "known_403":
        raise CloudRejected(403, "host_binding_renewal_rejected")
    if behavior == "known_422":
        raise CloudRejected(422, "client_admission_rejected")
    if behavior == "unknown_409":
        raise CloudRejected(409, "unclassified_problem")
    accepted.setdefault(kwargs["key"], kwargs["body"])
    assert accepted[kwargs["key"]] == kwargs["body"]
    if behavior == "lost_ack" and first:
        first = False
        raise Rejected("unknown acceptance")
    return {"status": "accepted"}


cloud.request = request


def retry(op):
    return chat.retry_fresh(doc.name, predecessor, eid, op)


def refuses(fn):
    try:
        fn()
    except Rejected:
        return
    raise AssertionError("expected bounded rejection")


op = reset()
result = retry(op)
assert result["status"] == "accepted" and len(accepted) == 1
before = len(calls)
assert retry(op)["run_id"] == result["run_id"] and len(calls) == before
assert doc.pending_command is None and doc.active_run_id != predecessor
print(
    "PASS BFF one explicit empty-message RUN, committed intent before"
    " network, native client surface, duplicate operation replay"
)

op = reset("lost_ack")
refuses(lambda: retry(op))
pinned = doc.pending_command
run = doc.active_run_id
refuses(lambda: retry(str(uuid4())))
revision = 99
result = retry(op)
posts = [k for m, p, k in calls if p == "/agui/commands"]
assert len(accepted) == 1 and posts[0]["body"] == posts[1]["body"] == json.loads(pinned)
assert posts[1]["body"]["expectedRevision"] == 3 and doc.active_run_id == run
print(
    "PASS BFF unknown AG-UI acceptance reuses immutable body/key/revision/Run despite newer header"
)

op = reset("unknown_409")
refuses(lambda: retry(op))
assert (
    doc.pending_command and json.loads(doc.request_options)["fresh_retry"]["phase"] == "dispatching"
)
print("PASS BFF known HTTP status with unknown reason retains immutable pending command")

op = reset("known_reject")
refuses(lambda: retry(op))
assert not doc.pending_command and doc.active_run_id == predecessor
assert json.loads(doc.request_options)["fresh_retry"]["phase"] == "rejected"
before = len(calls)
assert retry(op)["status"] == "rejected" and len(calls) == before
behavior = "allow"
assert retry(str(uuid4()))["status"] == "accepted"
print(
    "PASS BFF exact native pre-accept rejection restores predecessor;"
    " repeat returns same rejection, new explicit operation can reval"
    "idate"
)

op = reset("unknown_open")
refuses(lambda: retry(op))
opening = json.loads(doc.client_surface_json)
assert doc.active_run_id == predecessor and not doc.pending_command
refuses(lambda: retry(op))
assert sum(p.endswith("/client-surface") for m, p, k in calls) == 1
assert json.loads(doc.client_surface_json) == opening
opening["opening_at"] -= 421
doc.client_surface_json = json.dumps(opening)
behavior = "allow"
result = retry(op)
assert result["run_id"] == opening["opening_run"]
print(
    "PASS BFF actual native opening_run 420-second fence survives unk"
    "nown open, resumes same planned Run"
)

op = reset("unknown_release")
doc.client_surface_json = json.dumps(
    dict(
        runId=predecessor,
        clientSessionId="previous",
        taskId=doc.task_id,
        runBindingId="old-binding",
        sessionCredential="test-only",
        controllerFenceToken="old-fence",
    )
)
refuses(lambda: retry(op))
assert (
    doc.active_run_id == predecessor and json.loads(doc.client_surface_json)["runId"] == predecessor
)
behavior = "allow"
assert retry(op)["status"] == "accepted"
print("PASS BFF unknown client release retains old surface and same operation intent")

op = reset("grant_denied")
refuses(lambda: retry(op))
assert doc.active_run_id == predecessor and not doc.pending_command
behavior = "allow"
assert retry(op)["status"] == "accepted"
header = {
    "status": "ready",
    "command_outcome": {
        "code": "erp_fresh_authority_refused",
        "run_id": predecessor,
        "accepted_event_id": eid,
        "retry_eligible": True,
    },
}
state = history.public_state(header)
assert (
    state["status"] == "blocked"
    and state["canonical_status"] == "ready"
    and state["run_state"]["availableActions"] == ["retry"]
)
assert history.public_state({"status": "ready"})["status"] == "ready"
print(
    "PASS BFF permission failure keeps predecessor visible; cold stat"
    "e preserves canonical status and fixed native retry action"
)

# A later pre-idempotency rejection cannot disprove an earlier accepted POST.
for rejection in ["known_403", "known_422"]:
    op = reset("lost_ack")
    refuses(lambda *, op=op: retry(op))
    pinned = doc.pending_command
    run = doc.active_run_id
    behavior = rejection
    refuses(lambda *, op=op: retry(op))
    assert len(accepted) == 1 and doc.pending_command == pinned and doc.active_run_id == run
    assert json.loads(doc.request_options)["fresh_retry"]["phase"] == "dispatching"
    behavior = "allow"
    assert retry(op)["run_id"] == run
    posts = [k for m, p, k in calls if p == "/agui/commands"]
    assert len(accepted) == 1 and len(posts) == 3
    assert all(k["body"] == json.loads(pinned) and k["key"] == posts[0]["key"] for k in posts)
print(
    "PASS BFF accepted lost ACK then renewal403/client422 preserves s"
    "ame Run/body/key; restored authority admits one command"
)


# Durable dispatching is unknown even if interruption happened before the send.
class Interrupted(BaseException):
    pass


op = reset()
normal_commit = frappe.db.commit


def interrupted_commit():
    normal_commit()
    if json.loads(doc.request_options)["fresh_retry"]["phase"] == "dispatching":
        raise Interrupted()


frappe.db.commit = interrupted_commit
try:
    retry(op)
except Interrupted:
    pass
else:
    raise AssertionError("expected interruption after durable dispatching")
frappe.db.commit = normal_commit
pinned = doc.pending_command
run = doc.active_run_id
assert not accepted and pinned
behavior = "known_403"
refuses(lambda: retry(op))
assert not accepted and doc.pending_command == pinned and doc.active_run_id == run
behavior = "allow"
assert retry(op)["run_id"] == run and len(accepted) == 1
print(
    "PASS BFF interruption after durable dispatching before POST rema"
    "ins conservatively pinned across later rejection"
)
