"""Offline adapter regressions with no HTTP/model/search; python3
tests/test_full_capability_checks.py.
"""

import datetime
import json
import sys
import types
from pathlib import Path


class Refused(Exception):
    pass


frappe = types.ModuleType("frappe")
frappe.throw = lambda message, *_: (_ for _ in ()).throw(Refused(message))
frappe.PermissionError = frappe.ValidationError = Refused
utils = types.ModuleType("frappe.utils")
utils.now_datetime = datetime.datetime.now
sys.modules["frappe.utils"] = utils
frappe.parse_json = json.loads
sys.modules["frappe"] = frappe
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import requests as requests
except ImportError:
    sys.modules["requests"] = types.ModuleType("requests")
cloud = __import__("zebra_erpnext", fromlist=("cloud",)).cloud
extensions = __import__("zebra_erpnext", fromlist=("extensions",)).extensions
knowledge = __import__("zebra_erpnext", fromlist=("knowledge",)).knowledge
runtime = __import__("zebra_erpnext", fromlist=("runtime",)).runtime

new = types.SimpleNamespace(
    name="owned",
    runtime_ref="cloud114",
    preferences_json="{}",
    user="alice",
    company="A",
    task_id="task",
)
base = {
    "runtimes": {
        "cloud114": {
            "enabled": True,
            "base_url": "https://full.example",
            "namespace_id": "erpnext-full",
            "capabilities": {"extensions": True, "knowledge": True},
        }
    }
}
cloud.owned = lambda _: new
cloud.config = lambda: base
calls = []


def request(doc, method, path, **kwargs):
    calls.append((method, path, kwargs))
    if method == "GET":
        return dict(installation_id="skill-one", enabled=True, version={"skill_id": "read-guide"})
    return dict(ok=True)


cloud.request = request
new.preferences_json = json.dumps({"extension_selection": {"skills": ["skill-one"]}})
assert extensions.task_skills(new) == ["read-guide"]
assert calls[-1][1] == "/v1/extensions/skill-installations/skill-one"
for value in ["../escape", "a/b", "", "x" * 129]:
    try:
        extensions.identifier(value)
    except Refused:
        pass
    else:
        raise AssertionError("invalid path accepted")
knowledge.memory("owned", action="create", text="A confirmed preference")
assert calls[-1][1] == "/users/alice/memory" and calls[-1][2]["body"]["source_task_id"] == "task"
assert calls[-1][2]["body"]["operator"] == "alice"
foreign = types.SimpleNamespace(user="bob", company="A", status="active")
frappe.get_doc = lambda *a: foreign
try:
    knowledge.source(new, "foreign")
except Refused:
    pass
else:
    raise AssertionError("foreign source leaked")
new.runtime_ref = "native105"
for operation in [lambda: extensions.inventory("owned"), lambda: knowledge.inventory("owned")]:
    before = len(calls)
    try:
        operation()
    except Refused:
        pass
    else:
        raise AssertionError("legacy release gained full capability")
    assert len(calls) == before
print(
    "selected Skill mapping, exact RPC paths, memory owner, foreign source and legacy guards passed"
)

# Frappe Document.db_insert mutates the record and returns None (not a fluent API).
new.runtime_ref = "cloud114"
record = types.SimpleNamespace(
    name="knowledge-one", title="QA note", db_insert=lambda: None, db_update=lambda: None
)
file = types.SimpleNamespace(
    name="file-one", db_set=lambda field, value, **_: setattr(file, field, value)
)
file.insert = lambda **_: file
frappe.db = types.SimpleNamespace(count=lambda *_: 0)
frappe.get_doc = lambda value: record if value["doctype"] == "Zebra Knowledge" else file
created = knowledge.create(
    "owned", "QA note", dict(file_name="qa.txt", media_type="text/plain", content_base64="UUE=")
)
assert (
    created == dict(name="knowledge-one", title="QA note")
    and record.file_id == "file-one"
    and file.owner == "Administrator"
)
print("real db_insert return contract regression passed")
