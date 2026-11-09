"""Run: python3 tests/test_chat_checks.py. No Redis, database, or Cloud writes.

Exercise the real submit flow with a shared lock double: grant commits happen
while another caller tries admission, rather than merely checking source text.
Native Redis expiry/availability and deployed HTTP remain integration checks.
"""

import base64
import json
import sys
import threading
import types
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class Rejected(Exception):
    pass


class LockError(Exception):
    pass


class Doc:
    def __init__(self):
        self.name = "conversation"
        self.task_id = "task"
        self.active_run_id = "old-run"
        self.request_id = str(uuid4())
        self.pending_message = "old"
        self.request_options = None
        self.preferences_json = None
        self.pending_command = None
        self.stop_command = None
        self.prepared_request = None
        self.prepared_revision = 0
        self.status = "running"
        self.client_surface_json = None
        self.title = "Title"

    def reload(self):
        pass

    def db_update(self):
        pass

    def update(self, values):
        self.__dict__.update(values)


locks = {}


class SharedLock:
    def __init__(self, name, **kwargs):
        self.lock = locks.setdefault(name, threading.Lock())

    def __enter__(self):
        if not self.lock.acquire(blocking=False):
            raise LockError()
        return self

    def owned(self):
        return self.lock.locked()

    def __exit__(self, *args):
        self.lock.release()


frappe = types.ModuleType("frappe")
frappe.throw = lambda message, *args: (_ for _ in ()).throw(Rejected(message))
frappe.cache = types.SimpleNamespace(lock=SharedLock)
frappe.parse_json = json.loads
commits = []
frappe.db = types.SimpleNamespace(
    get_value=lambda *args, **kwargs: None, commit=lambda: commits.append("grant-commit")
)
utils = types.ModuleType("frappe.utils")
utils.now_datetime = lambda: None
redis = types.ModuleType("redis")
exceptions = types.ModuleType("redis.exceptions")
exceptions.LockError = LockError
cloud = types.ModuleType("zebra_erpnext.cloud")


class CloudRejectedError(Rejected):
    def __init__(self, status, reason):
        self.status_code = status
        super().__init__(reason)


cloud.CloudRejectedError = CloudRejectedError
cloud.has_private_workspace = lambda doc: True
cloud.require_admission_open = lambda *args: None
client = types.ModuleType("zebra_erpnext.client")
surface_calls = []
client.open_surface = lambda *args: surface_calls.append(args) or None
sys.modules.update(
    {
        "frappe": frappe,
        "frappe.utils": utils,
        "redis": redis,
        "redis.exceptions": exceptions,
        "zebra_erpnext.cloud": cloud,
        "zebra_erpnext.client": client,
    }
)
chat = __import__("zebra_erpnext", fromlist=("chat",)).chat

doc = Doc()
cloud.owned = lambda name, **kwargs: doc
cloud.config = lambda: {}
entered_header = threading.Event()
release_header = threading.Event()
requests = []
fail_command = False


def request(doc, method, path, **kwargs):
    # The production grant deliberately commits, invalidating DB row locks.
    frappe.db.commit()
    requests.append((method, path, kwargs))
    if path.endswith("/header"):
        entered_header.set()
        assert release_header.wait(5), "Concurrency check timed out"
        return {"current_turn_status": "completed"}
    if path.endswith("/messages"):
        return {"active_segment_sequence": 11}
    if path == "/agui/commands":
        if fail_command:
            raise Rejected("Cloud response lost")
        return {"status": "accepted"}
    raise AssertionError(path)


cloud.request = request
request_id = str(uuid4())
errors = []


def first_submit():
    try:
        chat.submit(doc.name, "new message", request_id)
    except Exception as error:
        errors.append(error)


thread = threading.Thread(target=first_submit)
thread.start()
try:
    assert entered_header.wait(5)
    assert commits, "Did not reach the grant commit under admission lock"
    try:
        chat.submit(doc.name, "competing message", str(uuid4()))
    except Rejected:
        pass
    else:
        raise AssertionError("Concurrent submit escaped the shared admission lock")
    assert len(requests) == 1, "Competing caller reached Cloud despite first caller's commit"
finally:
    release_header.set()
    thread.join(5)
assert not thread.is_alive()
assert not errors, errors
assert len([call for call in requests if call[1] == "/agui/commands"]) == 1
assert len([call for call in requests if call[1].endswith("/messages")]) == 1
assert doc.request_id == request_id

# A lost browser response reuses the same coordinates without another dispatch.
count = len(requests)
again = chat.submit(doc.name, "new message", request_id)
assert again["run_id"] == doc.active_run_id
assert len(requests) == count

# A lost Cloud command acknowledgement keeps a byte-identical durable command.
doc.status = "completed"
next_id = str(uuid4())
fail_command = True
try:
    chat.submit(doc.name, "follow-up", next_id)
except Rejected:
    pass
else:
    raise AssertionError("Expected lost command acknowledgement")
saved_command = doc.pending_command
saved_surface_count = len(surface_calls)
fail_command = False
chat.submit(doc.name, "follow-up", next_id)
commands = [call for call in requests if call[1] == "/agui/commands"]
assert commands[-1][2]["body"] == json.loads(saved_command)
assert commands[-1][2]["key"] == commands[-2][2]["key"]
assert len(surface_calls) == saved_surface_count, "Pinned command retry reopened a client surface"
print(
    "Shared admission survives grant commits; duplicate and lost-ack "
    "retries preserve dispatch coordinates"
)

# A lost stop acknowledgement must replay the exact revision under the same key.
fail_command = True
try:
    chat.cancel(doc.name)
except Rejected:
    pass
else:
    raise AssertionError("Expected lost stop acknowledgement")
pinned_stop = json.loads(doc.stop_command)
fail_command = False
before = len(requests)
chat.cancel(doc.name)
assert not any(path.endswith("/header") for _, path, _ in requests[before:])
assert requests[-1][2]["body"] == pinned_stop
print("Stop acknowledgement loss preserves the pinned command revision")

# First-task preparation must survive a client surface credential ACK loss.
doc.task_id = None
doc.status = "idle"
doc.pending_command = None
doc.request_id = None
doc.prepared_request = None
first_id = str(uuid4())
before = len(requests)
original_request = cloud.request
cloud.request = (
    lambda d, m, p, **kw: (
        requests.append((m, p, kw)) or {"task_id": "first-task", "current_sequence": 2}
    )
    if p == "/tasks"
    else original_request(d, m, p, **kw)
)
client.open_surface = lambda *args: (_ for _ in ()).throw(Rejected("surface ACK unknown"))
for _ in range(2):
    try:
        chat.submit(doc.name, "first question", first_id)
    except Rejected:
        pass
    else:
        raise AssertionError("Expected unknown surface")
new_requests = requests[before:]
assert len([p for _, p, _ in new_requests if p == "/tasks"]) == 1
assert not any(p.endswith("/messages") or p == "/agui/commands" for _, p, _ in new_requests)
print("First task preparation survives surface ACK loss without duplicating the user message")

# Conversation management shares admission and never deletes business records.
doc.task_id = None
doc.status = "idle"
doc.pending_command = None
removed = []
expired = []
frappe.db.delete = lambda table, filters: removed.append((table, filters))


def management_set_value(table, name, field, value=None, **kwargs):
    if table == "Zebra Conversation":
        assert locks["zebra:submit:" + name].locked()
        doc.update(field)
    else:
        expired.append((table, name, field, value))


frappe.db.set_value = management_set_value
assert chat.manage(doc.name, title="  更名验收  ")["title"] == "更名验收"
for title in ["", "   ", "x" * 121, None]:
    try:
        chat.manage(doc.name, title=title)
    except Rejected:
        pass
    else:
        raise AssertionError("Invalid title accepted")
with SharedLock("zebra:submit:" + doc.name):
    try:
        chat.manage(doc.name, delete=True)
    except Rejected:
        pass
    else:
        raise AssertionError("Delete escaped submit admission")
doc.task_id = "task"
cloud.request = lambda *args, **kwargs: {"current_turn_status": "running"}
try:
    chat.manage(doc.name, delete=True)
except Rejected:
    pass
else:
    raise AssertionError("Running conversation deleted")
assert not removed and not expired
cloud.request = lambda *args, **kwargs: {"current_turn_status": "completed"}
assert chat.manage(doc.name, delete=True)["deleted"]
assert doc.status == "deleted"
assert removed == [("Zebra Grant", {"conversation": doc.name})]
assert expired[0][0] == "Zebra Business Approval"
print(
    "Rename validation, shared delete admission, running-task rejecti"
    "on and approval/grant revocation passed"
)

# Model/effort selection reaches native initial admission and continuation.
doc = Doc()
doc.task_id = None
doc.status = "idle"
doc.request_id = None
cloud.request = (
    lambda d, m, p, **kw: (
        requests.append((m, p, kw)) or {"task_id": "options-task", "current_sequence": 2}
    )
    if p == "/tasks"
    else request(d, m, p, **kw)
)
client.open_surface = lambda *args: None
pro = "deepseek-v4-pro-executor-v1"
flash = "deepseek-v4-flash-executor-v1"
choice_id = str(uuid4())
before = len(requests)
chat.submit(doc.name, "options first", choice_id, model_profile=pro, reasoning_effort="max")
first = next(kw["body"] for m, p, kw in requests[before:] if p == "/tasks")
assert first["model_profile"] == pro and first["reasoning_effort"] == "max"
assert requests[-1][2]["body"]["input"]["state"] == {}, (
    "Model options must not leak into the registered frontend state schema"
)
count = len(requests)
try:
    chat.submit(doc.name, "options first", choice_id, model_profile=flash, reasoning_effort="low")
except Rejected:
    pass
else:
    raise AssertionError("Same request silently changed model")
assert len(requests) == count
for bad in [
    {"model_profile": "untrusted"},
    {"model_profile": []},
    {"reasoning_effort": ""},
    {"reasoning_effort": "medium"},
]:
    try:
        chat.submit(doc.name, "invalid options", str(uuid4()), **bad)
    except Rejected:
        pass
    else:
        raise AssertionError("Unsupported options accepted")
assert len(requests) == count
next_id = str(uuid4())
fail_command = True
try:
    chat.submit(
        doc.name, "options follow-up", next_id, model_profile=flash, reasoning_effort="none"
    )
except Rejected:
    pass
else:
    raise AssertionError("Expected lost command ACK")
saved = doc.pending_command
before = len(requests)
fail_command = False
chat.submit(doc.name, "options follow-up", next_id, model_profile=flash, reasoning_effort="none")
assert requests[-1][2]["body"] == json.loads(saved)
assert not any(p.endswith("/messages") for _, p, _ in requests[before:])
body = next(kw["body"] for _, p, kw in reversed(requests) if p.endswith("/messages"))
assert body["model_profile"] == flash and body["reasoning_effort"] == "none"
for item in chat.REASONING_OPTIONS:
    assert chat.run_options(flash, item["value"])["reasoning_effort"] == item["value"]
print(
    "Model and effort propagate on first/follow-up turns; invalid or "
    "changed retry options rejected; lost ACK preserves settings"
)

# A mounted client surface permits only its registered ERP page readable.
doc = Doc()
doc.task_id = None
doc.status = "idle"
doc.request_id = None
client.open_surface = lambda *args: {"clientSessionId": "browser"}
cloud.config = lambda: {"frontend_profile": {"actions": [], "digest": "b" * 64}}
chat.submit(
    doc.name,
    "client state check",
    str(uuid4()),
    {"route": ["Workspaces", "Home"]},
    model_profile=pro,
    reasoning_effort="low",
)
assert requests[-1][2]["body"]["input"]["state"] == {
    "erpnext.ui.context": {"route": ["Workspaces", "Home"]}
}
print("Client-surface state remains within the published ERP readable schema")

# Per-conversation choices are distinct from immutable dispatch coordinates.
doc.company = "QA"
doc.request_options = json.dumps({"model_profile": pro, "reasoning_effort": "max"})
assert chat.settings(doc.name)["reasoning_effort"] == "max", "Legacy choices not restored"
old_request = doc.request_options
frappe.db.set_value = lambda table, name, field, value, **kwargs: setattr(doc, field, value)
before_save_commits = len(commits)
chat.save_settings(doc.name, flash, "low")
assert len(commits) == before_save_commits + 1, "Preference save released admission before commit"
assert chat.settings(doc.name) == {
    "model_profile": flash,
    "reasoning_effort": "low",
    "company": "QA",
}
assert doc.request_options == old_request, "Preferences overwrote retry identity"
second = Doc()
second.company = "Another"
second.preferences_json = json.dumps({"model_profile": pro, "reasoning_effort": "none"})
cloud.owned = lambda name, **kwargs: doc if name == doc.name else second
assert chat.settings("another")["reasoning_effort"] == "none"
assert chat.settings(doc.name)["reasoning_effort"] == "low"
with SharedLock("zebra:submit:" + doc.name):
    try:
        chat.save_settings(doc.name, pro, "high")
    except Rejected:
        pass
    else:
        raise AssertionError("Preference save raced submit")
assert chat.settings(doc.name)["reasoning_effort"] == "low"
print(
    "Conversation preferences restore independently, inherit legacy c"
    "hoices, preserve retry coordinates and share submission admissio"
    "n"
)

# Page coordinates join model/files in immutable retry admission. The grant
# commits remain inside the shared submit lock, and a changed context fails
# before any Cloud call, including after a proven accepted result.
doc = Doc()
doc.task_id = None
doc.status = "idle"
doc.request_id = None
cloud.owned = lambda name, **kwargs: doc
cloud.config = lambda: {}
client.open_surface = lambda *args: None
cloud.request = (
    lambda d, m, p, **kw: (
        requests.append((m, p, kw)) or {"task_id": "context-task", "current_sequence": 2}
    )
    if p == "/tasks"
    else request(d, m, p, **kw)
)
original_page = {"route": ["Form", "Customer", "C1"], "doctype": "Customer", "name": "C1"}
changed_page = {"route": ["Form", "Customer", "C2"], "doctype": "Customer", "name": "C2"}
context_id = str(uuid4())
fail_command = True
try:
    chat.submit(doc.name, "context retry", context_id, original_page)
except Rejected:
    pass
else:
    raise AssertionError("Expected lost command ACK")
pinned_context_command = doc.pending_command
assert json.loads(doc.request_options)["context"] == original_page
before = (len(requests), len(commits))
try:
    chat.submit(doc.name, "context retry", context_id, changed_page)
except Rejected as error:
    assert "上下文" in str(error)
else:
    raise AssertionError("Unknown-result retry changed page")
assert (len(requests), len(commits)) == before
fail_command = False
chat.submit(doc.name, "context retry", context_id, json.dumps(original_page, sort_keys=True))
assert requests[-1][2]["body"] == json.loads(pinned_context_command)
before = len(requests)
try:
    chat.submit(doc.name, "context retry", context_id, changed_page)
except Rejected:
    pass
else:
    raise AssertionError("Accepted request changed page binding")
assert len(requests) == before
# An existing pre-upgrade command has the original context in its Host guidance.
legacy = json.loads(doc.request_options)
legacy.pop("context")
doc.request_options = json.dumps(legacy)
doc.pending_command = pinned_context_command
doc.status = "dispatching"
before = len(requests)
try:
    chat.submit(doc.name, "context retry", context_id, changed_page)
except Rejected:
    pass
else:
    raise AssertionError("Legacy pinned command accepted changed page")
assert len(requests) == before
chat.submit(doc.name, "context retry", context_id, original_page)
assert json.loads(doc.request_options)["context"] == original_page
assert requests[-1][2]["body"] == json.loads(pinned_context_command)
# Already-accepted legacy records lacking a command acquire a binding once.
legacy = json.loads(doc.request_options)
legacy.pop("context")
doc.request_options = json.dumps(legacy)
before = len(requests)
chat.submit(doc.name, "context retry", context_id, original_page)
assert json.loads(doc.request_options)["context"] == original_page and len(requests) == before
print(
    "PASS immutable page context, pre-dispatch and accepted retry rej"
    "ection, byte-identical command reuse and legacy request compatib"
    "ility"
)

# File coordinates are immutable on retries and propagate through native admission.

doc = Doc()
doc.task_id = None
doc.status = "idle"
doc.request_id = None
cloud.owned = lambda name, **kwargs: doc
cloud.config = lambda: {"attachments_enabled": True}
cloud.has_private_workspace = lambda d: True
client.open_surface = lambda *args: None
cloud.request = (
    lambda d, m, p, **kw: (
        requests.append((m, p, kw)) or {"task_id": "file-task", "current_sequence": 2}
    )
    if p == "/tasks"
    else request(d, m, p, **kw)
)
files = [
    {
        "file_name": "proof.txt",
        "media_type": "text/plain",
        "content_base64": base64.b64encode(b"owned file").decode(),
    }
]
file_id = str(uuid4())
before = len(requests)
fail_command = True
try:
    chat.submit(doc.name, "read the file", file_id, attachments=json.dumps(files))
except Rejected:
    pass
else:
    raise AssertionError("Expected unknown dispatch response")
pinned = doc.pending_command
assert next(kw["body"]["attachments"] for _, p, kw in requests[before:] if p == "/tasks") == files
assert (
    "attachments" not in json.loads(pinned)["input"]["messages"][0]
)  # bytes are admitted once via Task/message, not AG-UI
before = len(requests)
changed = [dict(files[0], content_base64=base64.b64encode(b"changed").decode())]
try:
    chat.submit(doc.name, "read the file", file_id, attachments=changed)
except Rejected:
    pass
else:
    raise AssertionError("Same request accepted changed file")
assert len(requests) == before
fail_command = False
chat.submit(doc.name, "read the file", file_id, attachments=files)
assert requests[-1][2]["body"] == json.loads(pinned)
cloud.has_private_workspace = lambda d: False
before = len(requests)
try:
    chat.submit(doc.name, "private legacy upload", str(uuid4()), attachments=files)
except Rejected:
    pass
else:
    raise AssertionError("Private files admitted into shared legacy workspace")
assert len(requests) == before
cloud.has_private_workspace = lambda d: True

# A proven native 400 admission rejection must not strand dispatching forever.
doc = Doc()
doc.task_id = None
doc.status = "idle"
doc.request_id = None
cloud.request = lambda *a, **k: (_ for _ in ()).throw(CloudRejectedError(400, "invalid_document"))
try:
    chat.submit(doc.name, "invalid document", str(uuid4()), attachments=files)
except CloudRejectedError:
    pass
else:
    raise AssertionError("Expected native admission rejection")
assert doc.status == "rejected" and not doc.pending_command
print(
    "PASS file admission/digest/retry binding, private legacy upload "
    "fence and known rejection recovery"
)

cloud.config = lambda: {"attachments_enabled": False}
before = len(requests)
try:
    chat.submit(doc.name, "upload disabled", str(uuid4()), attachments=files)
except Rejected as e:
    assert "暂停上传" in str(e)
else:
    raise AssertionError("Unverified ingress accepted upload")
assert len(requests) == before
print("PASS unverified attachment ingress fails closed before Cloud mutation")

cloud.require_admission_open = lambda *args: (_ for _ in ()).throw(Rejected("maintenance"))
before = (len(requests), len(commits), dict(doc.__dict__))
for action in (
    lambda: chat.submit(doc.name, "paused", str(uuid4())),
    lambda: chat.cancel(doc.name),
):
    try:
        action()
    except Rejected as e:
        assert str(e) == "maintenance"
    else:
        raise AssertionError("Paused admission entered mutation")
assert (len(requests), len(commits), doc.__dict__) == before
print("PASS maintenance pauses submit/cancel before request coordinates or Cloud writes")
