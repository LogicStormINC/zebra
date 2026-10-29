"""Run: python3 tests/test_cancel_clears_pending.py
A confirmed stop must discharge the undelivered retry payload, otherwise the
stale pending_command keeps blocking deletion with the dispatching guard.
"""
import importlib.util
import json
from pathlib import Path
import sys
import types


class Rejected(Exception):
    pass


frappe = types.ModuleType('frappe')
frappe.throw = lambda message, *args: (_ for _ in ()).throw(Rejected(message))
frappe.PermissionError = Rejected
frappe.parse_json = json.loads
frappe.db = types.SimpleNamespace(commit=lambda: None)


class _Cache:
    def lock(self, *args, **kwargs):
        import contextlib

        @contextlib.contextmanager
        def held():
            yield types.SimpleNamespace(owned=lambda: True)

        return held()


frappe.cache = _Cache()

frappe_utils = types.ModuleType('frappe.utils')
frappe_utils.now_datetime = lambda: '2026-10-29T00:00:00'
sys.modules.update({'frappe': frappe, 'frappe.utils': frappe_utils})

cloud = types.ModuleType('zebra_erpnext.cloud')
cloud.require_admission_open = lambda *args: None
runtime = types.ModuleType('zebra_erpnext.runtime')
runtime.LEGACY = 'native105'
runtime.FULL = 'cloud114'
runtime.release = lambda doc: runtime.LEGACY
runtime.settings = lambda doc, base: base
extensions = types.ModuleType('zebra_erpnext.extensions')
zebra_pkg = types.ModuleType('zebra_erpnext')
zebra_pkg.cloud = cloud
zebra_pkg.runtime = runtime
zebra_pkg.extensions = extensions
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules.update({'zebra_erpnext': zebra_pkg, 'zebra_erpnext.cloud': cloud,
                    'zebra_erpnext.runtime': runtime, 'zebra_erpnext.extensions': extensions})

spec = importlib.util.spec_from_file_location('zebra_erpnext.chat', Path(__file__).resolve().parents[1] / 'zebra_erpnext' / 'chat.py')
chat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chat)


class Doc:
    name = 'conversation'
    user = 'user'
    status = 'dispatching'
    task_id = 'task-id'
    active_run_id = 'run-id'
    request_id = 'req'
    stop_command = None
    pending_command = '{"action":"run"}'
    pending_message = '请打开生产计划'
    updates = []

    def db_update(self):
        self.updates.append(self.status)


doc = Doc()
cloud.owned = lambda name, **kwargs: doc
cloud.request = lambda doc, method, path, **kwargs: {'status': 'running'} if method == 'GET' else {}

chat.cancel('conversation')

assert doc.status == 'cancelled', 'cancel confirms the terminal status'
assert doc.pending_command is None, 'a confirmed stop discharges the retry payload'
assert doc.pending_message is None, 'the mirrored pending message is discharged too'
# Guard parity with manage(): deletion no longer sees a stale pending command.
assert not (doc.pending_command or doc.status == 'dispatching'), 'delete guard would no longer block'
print('PASS confirmed cancel discharges pending retry payload (deletion no longer blocked)')


class ConflictDoc(Doc):
    def __init__(self):
        self.name = 'conversation'
        self.user = 'user'
        self.status = 'running'
        self.task_id = 'task-id'
        self.active_run_id = 'run-id'
        self.request_id = 'req'
        self.stop_command = None
        self.pending_command = None
        self.pending_message = None
        self.updates = []


conflict_doc = ConflictDoc()
cloud.owned = lambda name, **kwargs: conflict_doc


def conflict_request(doc, method, path, **kwargs):
    if method == 'GET':
        return {'status': 'running', 'active_segment_sequence': 7}
    raise cloud.CloudRejectedError  # placeholder replaced below


class CloudRejected(Exception):
    pass


cloud.CloudRejectedError = type('CloudRejectedError', (Exception,), {'reason': 'revision_conflict'})


def stop_once(doc, method, path, **kwargs):
    if method == 'GET':
        return {'status': 'running', 'active_segment_sequence': 7}
    raise cloud.CloudRejectedError('409')


cloud.request = stop_once
try:
    chat.cancel('conversation')
    raise AssertionError('conflict propagates')
except cloud.CloudRejectedError:
    pass
assert conflict_doc.stop_command is None, 'revision_conflict drops the stale cached stop for rebuild'
print('PASS revision_conflict drops the stale cached stop command')
