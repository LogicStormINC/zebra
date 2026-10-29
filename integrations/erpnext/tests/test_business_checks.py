"""Run: python3 tests/test_business_checks.py (stdlib only; no live database).

These contract checks complement, rather than replace, live Frappe permission tests.
"""
import datetime
import json
from pathlib import Path
import sys
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class Attr(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__


class Rejected(Exception):
    pass


frappe = types.ModuleType("frappe")
frappe.whitelist = lambda **kwargs: lambda fn: fn
frappe.PermissionError = frappe.ValidationError = Rejected
frappe.throw = lambda message, *args: (_ for _ in ()).throw(Rejected(message))
frappe.session = Attr(user="alice", sid="session-alice", data=Attr(csrf_token="csrf-alice"))
frappe.flags = Attr()
frappe.local = Attr(request=Attr(method="POST", cookies={"sid": "session-alice"}))
headers = {"X-Frappe-CSRF-Token": "csrf-alice"}
frappe.get_request_header = headers.get
frappe.parse_json = json.loads
frappe.as_json = lambda value: json.dumps(value, default=str)
utils = types.ModuleType("frappe.utils")
utils.now_datetime = datetime.datetime.now
utils.get_datetime = lambda value: value if isinstance(value, datetime.datetime) else datetime.datetime.fromisoformat(value)
sys.modules.update({"frappe": frappe, "frappe.utils": utils})

from zebra_erpnext import business as b
from zebra_erpnext import capabilities as c


def rejects(fn, text=None):
    try:
        fn()
    except Rejected as exc:
        assert text is None or text in str(exc), str(exc)
    else:
        raise AssertionError("Expected request rejection")


class Meta:
    name = "Sales Order"
    issingle = istable = is_virtual = False
    fields = [Attr(fieldname="customer", fieldtype="Link", read_only=False),
              Attr(fieldname="company", fieldtype="Link", read_only=False),
              Attr(fieldname="secret", fieldtype="Password", read_only=False),
              Attr(fieldname="private", fieldtype="Data", read_only=False),
              Attr(fieldname="masked", fieldtype="Data", mask=1, read_only=False),
              Attr(fieldname="read_only", fieldtype="Data", read_only=True)]

    def get_field(self, name):
        return next((f for f in self.fields if f.fieldname == name), None)

    def get_permitted_fieldnames(self, **kwargs):
        # Native Frappe deliberately omits Tables here.
        return [f.fieldname for f in self.fields if f.fieldname != "private" and f.fieldtype not in {"Table", "Table MultiSelect"}]

    def get_permlevel_access(self, **kwargs): return [0]
    def get_permissions(self, **kwargs): return [True]

    def has_field(self, field):
        return bool(self.get_field(field))


meta = Meta()
frappe.get_meta = lambda doctype: meta
frappe.has_permission = lambda *args, **kwargs: True
frappe.get_list = lambda *args, **kwargs: [Attr(name="ACME")]
frappe.get_hooks = lambda name: {}

assert c.readable_fields(meta) == {"customer", "company", "read_only"}
assert not c.mutable(Attr(name="User", issingle=False))
assert not c.mutable(Attr(name="System Settings", issingle=True))
assert c.mutable(meta)
rejects(lambda: b.checked_values(meta, {"flags": {"ignore_permissions": True}}), "not writable")
rejects(lambda: b.checked_values(meta, {"secret": "credential"}), "not writable")
rejects(lambda: b.checked_values(meta, {"private": "leak"}), "not writable")
rejects(lambda: b.checked_values(meta, {"customer": {"ignore_permissions": True}}), "scalar")
assert b.checked_values(meta, {"customer": "Customer A"}) == {"customer": "Customer A"}
rejects(lambda: b.validate("query", {"doctype": "Sales Order", "ignore_permissions": True}), "unsupported")
rejects(lambda: b.validate("query", {"doctype": "Sales Order", "fields": [float("nan")]}), "finite")
rejects(lambda: b.query({"doctype": "Sales Order", "fields": ["private"]}), "readable")
rejects(lambda: b.query({"doctype": "Sales Order", "fields": ["masked"]}), "readable")
rejects(lambda: b.query({"doctype": "Sales Order", "fields": ["count(*)"]}), "readable")
rejects(lambda: b.query({"doctype": "Sales Order", "filters": {"secret": "value"}}), "readable")
rejects(lambda: b.query({"doctype": "Sales Order", "limit": True}), "pagination")
rejects(lambda: b.query({"doctype": "Sales Order", "limit": 51}), "pagination")
rejects(lambda: b.query({"doctype": "Sales Order", "filters": {"customer": [["in"], "A"]}}), "operator")
rejects(lambda: b.query({"doctype": "Sales Order", "filters": {"customer": ["in", [{"sql": "bad"}]]}}), "operand")
rejects(lambda: b.query({"doctype": "Sales Order", "filters": {"customer": ["between", ["A"]]}}), "two")

rejects(lambda: b.check_company(Attr(doctype="Company", name="B", meta=meta), "A"), "outside")
class CompanyMeta(Meta):
    name = "Company"
frappe.get_meta = lambda doctype: CompanyMeta()
company_query = []
frappe.get_list = lambda *args, **kwargs: company_query.append(kwargs) or [Attr(name="A")]
b.query({"doctype": "Company", "company": "A", "fields": ["name"]})
assert company_query[-1]["filters"] == {"name": "A"}
rejects(lambda: b.write("create", {"doctype": "Company", "company": "A", "values": {"company": "B"}}), "administrative")
frappe.get_meta = lambda doctype: meta
frappe.get_list = lambda *args, **kwargs: [Attr(name="ACME")]

# Existing child identities must belong to the loaded document and exact table field.
class ChildMeta(Meta):
    name = "Sales Order Item"
    fields = [Attr(fieldname="item_code", fieldtype="Link", read_only=False),
              Attr(fieldname="qty", fieldtype="Float", read_only=False)]
class TableMeta(Meta):
    fields = Meta.fields + [Attr(fieldname="items", fieldtype="Table", options="Sales Order Item", read_only=False)]
class Child(Attr):
    def as_dict(self):
        return dict(self)
row = Child(name="ROW-1", parent="SO-1", parenttype="Sales Order", parentfield="items", item_code="ITEM-A", qty=1)
parent = Attr(name="SO-1", items=[row])
frappe.get_meta = lambda doctype: ChildMeta() if doctype == "Sales Order Item" else meta
updated = b.checked_values(TableMeta(), {"items": [{"name": "ROW-1", "qty": 2}]}, existing=parent)
assert updated["items"][0]["name"] == "ROW-1" and updated["items"][0]["item_code"] == "ITEM-A"
assert updated["items"][0]["qty"] == 2
rejects(lambda: b.checked_values(TableMeta(), {"items": [{"name": "FOREIGN", "qty": 2}]}, existing=parent), "does not belong")
rejects(lambda: b.checked_values(TableMeta(), {"items": [{"name": "ROW-1", "qty": 2}] * 2}, existing=parent), "does not belong")
row.parentfield = "other_items"
rejects(lambda: b.checked_values(TableMeta(), {"items": [{"name": "ROW-1", "qty": 2}]}, existing=parent), "does not belong")
frappe.get_meta = lambda doctype: meta
assert not c.mutable(Attr(name="File", issingle=False))
rejects(lambda: b.validate("settings_update", {"doctype": "System Settings", "name": "System Settings", "modified": "t", "values": {"disable_user_pass_login": 1}}), "locale/format")
assert b.validate("settings_update", {"doctype": "System Settings", "name": "System Settings", "modified": "t", "values": {"time_zone": "Asia/Shanghai"}})["values"] == {"time_zone": "Asia/Shanghai"}
rejects(lambda: b.attachment("upload_file", {"filename": "../private.txt", "content_base64": "aGVsbG8="}, Attr()), "filename/type")
rejects(lambda: b.attachment("upload_file", {"filename": "evil.html", "content_base64": "aGVsbG8="}, Attr()), "filename/type")
rejects(lambda: b.attachment("upload_file", {"filename": "test.txt", "content_base64": "not-base64"}, Attr()), "base64")

# Published actions use only a deployer-defined controller method and exact scalar args.
called = []
class ActionDocument:
    doctype = "Sales Order"
    def check_permission(self, permission):
        called.append(permission)
    def native_action(self, quantity):
        return {"quantity": quantity}
frappe.get_hooks = lambda name: {"calculate": [{"doctype": "Sales Order", "method": "native_action",
                                              "permission": "write", "parameters": {"quantity": "int"}}]}
frappe.is_whitelisted = lambda method: called.append("whitelisted")
frappe.allowed_http_methods_for_whitelisted_func = {ActionDocument.native_action: ["POST"]}
assert b.invoke_action(ActionDocument(), {"action": "calculate", "parameters": {"quantity": 3}}) == {"quantity": 3}
assert called == ["write", "whitelisted"]
rejects(lambda: b.invoke_action(ActionDocument(), {"action": "unpublished", "parameters": {}}), "not explicitly")
rejects(lambda: b.invoke_action(ActionDocument(), {"action": "calculate", "parameters": {"quantity": True}}), "parameter")
rejects(lambda: b.invoke_action(ActionDocument(), {"action": "calculate", "parameters": {"quantity": 3, "ignore_permissions": True}}), "schema")
frappe.get_hooks = lambda name: {"calculate": {"doctype": ["Sales Order"], "method": ["native_action"],
                                             "permission": ["write"], "parameters": {"quantity": ["int"]}}}
assert c.published_actions("Sales Order")["calculate"]["parameters"] == {"quantity": "int"}
assert b.invoke_action(ActionDocument(), {"action": "calculate", "parameters": {"quantity": 4}}) == {"quantity": 4}
frappe.get_hooks = lambda name: {}

# End-to-end approval state machine with an in-memory storage stand-in.
rows = {}
locks = []


class Record(Attr):
    def db_insert(self):
        assert not any(r.request_key == self.request_key for r in rows.values())
        rows[self.name] = Attr(self)


def get_value(doctype, filters, fields, as_dict=False, for_update=False):
    if for_update:
        locks.append(filters)
    row = rows.get(filters) if isinstance(filters, str) else next(
        (r for r in rows.values() if all(r.get(k) == v for k, v in filters.items())), None)
    return Attr({key: row.get(key) for key in fields}) if row else None


frappe.get_doc = lambda data: Record(data)
frappe.db = Attr(_disable_transaction_control=0, get_value=get_value,
                 set_value=lambda doctype, name, values: rows[name].update(values))
mutations = []
b.write = lambda operation, args: mutations.append((operation, args)) or {"created": "SO-1"}
args = {"doctype": "Sales Order", "values": {"customer": "Customer A"}, "company": "ACME"}
proposal = b.execute("create", args, "request-1")
assert proposal["approval_required"] and len(proposal["proposal_id"]) == 64
assert not mutations
assert rows[proposal["proposal_id"]].name != proposal["approval_token"]
rejects(lambda: b.execute("create", dict(args, values={"customer": "B"}), "request-1"), "different arguments")
rejects(lambda: b.execute("create", args, "request-2", proposal["approval_token"]), "does not match")
frappe.flags.zebra_tool_call = True
rejects(lambda: b.confirm(proposal["proposal_id"]), "browser session")
rejects(lambda: b.execute("create", args, "request-1", proposal["approval_token"]), "Tools cannot")
frappe.flags.zebra_tool_call = False
headers["X-Frappe-CSRF-Token"] = "wrong"
rejects(lambda: b.confirm(proposal["proposal_id"]), "browser session")
headers["X-Frappe-CSRF-Token"] = "csrf-alice"
headers["Authorization"] = "Bearer model-token"
rejects(lambda: b.confirm(proposal["proposal_id"]), "browser session")
headers.pop("Authorization")
frappe.session.user = "bob"
rejects(lambda: b.confirm(proposal["proposal_id"]), "not available")
frappe.session.user = "alice"
assert b.confirm(proposal["proposal_id"]) == {"created": "SO-1"}
assert b.confirm(proposal["proposal_id"]) == {"created": "SO-1"}
assert b.execute("create", args, "request-1") == {"created": "SO-1"}
assert len(mutations) == 1 and locks
assert frappe.db._disable_transaction_control == 0
expired = b.execute("create", args, "request-expired")
rows[expired["proposal_id"]].expires_at = datetime.datetime.now() - datetime.timedelta(seconds=1)
rejects(lambda: b.confirm(expired["proposal_id"]), "expired")
assert len(mutations) == 1
frappe.session.user = "Guest"
rejects(lambda: b.execute("query", {"doctype": "Sales Order"}, "guest"), "Sign in")
print("Business adapter checks passed: field/query boundaries, guest rejection, CSRF/session isolation, binding, expiry and replay.")
