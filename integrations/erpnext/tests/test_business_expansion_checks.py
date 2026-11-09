"""Run: python3 tests/test_business_expansion_checks.py; stdlib contract regressions."""

import csv
import importlib
import io
import runpy
import sys
import types
from pathlib import Path

ns = runpy.run_path(str(Path(__file__).with_name("test_business_checks.py")))
b = importlib.reload(ns["b"])
c, frappe, Attr, Meta, rejects = (ns[key] for key in ("c", "frappe", "Attr", "Meta", "rejects"))
frappe.session.user = "alice"


class NumericMeta(Meta):
    fields = Meta.fields + [Attr(fieldname="amount", fieldtype="Currency", read_only=False)]


meta = NumericMeta()
frappe.get_meta = lambda doctype: meta
calls = []
data = [
    Attr(name="ONE", amount="0.10", customer='=HYPERLINK("bad")'),
    Attr(name="TWO", amount="0.20", customer="normal"),
]
frappe.get_list = (
    lambda doctype, **kwargs: calls.append(kwargs) or data[: kwargs.get("limit_page_length", 20)]
)
page = b.query_page({"doctype": meta.name, "fields": ["name"], "limit": 1, "company": "ACME"})
assert page == {"rows": data[:1], "has_more": True, "next_start": 1}
assert calls[-1]["filters"] == {"company": "ACME"}
assert calls[-1]["limit_page_length"] == 2
assert b.query_page({"doctype": meta.name, "limit": 2})["next_start"] is None
rejects(lambda: b.query_page({"doctype": meta.name, "order_by": "secret desc"}), "Ordering")
rejects(lambda: b.query_page({"doctype": meta.name, "order_by": "name; drop table"}), "Ordering")
exported = b.export({"doctype": meta.name, "fields": ["customer"], "limit": 1})
assert (
    list(csv.reader(io.StringIO(exported["content"])))[1][0].startswith("'=HYPERLINK")
    and exported["has_more"]
)
frappe.has_permission = lambda doctype, permission: permission != "export"
rejects(lambda: b.export({"doctype": meta.name, "fields": ["customer"]}), "Export")
frappe.has_permission = lambda *args: True
assert b.aggregate({"doctype": meta.name, "metric": "sum", "field": "amount"})["value"] == "0.30"
assert b.aggregate({"doctype": meta.name, "metric": "count"})["value"] == 2
rejects(lambda: b.aggregate({"doctype": meta.name, "metric": "sum", "field": "secret"}), "numeric")
rejects(lambda: b.aggregate({"doctype": meta.name, "metric": []}), "metric")
frappe.get_list = lambda *args, **kwargs: [Attr(name=str(i)) for i in range(1001)]
rejects(lambda: b.aggregate({"doctype": meta.name, "metric": "count"}), "1000")
report_module = types.ModuleType("frappe.desk.query_report")


def report(name):
    if name == "private":
        b.fail("Report not accessible", True)
    return Attr(
        name=name,
        ref_doctype=meta.name,
        report_type="Script Report",
        filters=[Attr(fieldname="company", label="Company", fieldtype="Link", options="Company")],
        columns=[],
        javascript="secret",
        query="secret",
    )


report_module.get_report_doc = report
sys.modules["frappe.desk.query_report"] = report_module
assert b.report_describe("native")["filters"][0]["fieldname"] == "company"
assert "secret" not in str(b.report_describe("native"))
assert b.report_describe("native")["descriptor_complete"] is False
rejects(lambda: b.report_describe("private"), "accessible")
# Host read tools bind the selected company to every operation before execute().
frappe.get_list = lambda *args, **kwargs: [Attr(name="ACME")]
assert (
    b.execute("report_describe", {"report": "native", "company": "ACME"}, "host-report-describe")[
        "ref_doctype"
    ]
    == meta.name
)
rejects(
    lambda: b.execute(
        "report_describe", {"report": "private", "company": "ACME"}, "host-private-report"
    ),
    "accessible",
)
frappe.get_list = lambda *args, **kwargs: []
rejects(
    lambda: b.execute(
        "report_describe", {"report": "native", "company": "DENIED"}, "host-denied-company"
    ),
    "Company is not accessible",
)
comments = []
comment_permissions = []


class Document(Attr):
    def check_permission(self, permission):
        comment_permissions.append(permission)
        if self.get("denied"):
            b.fail("Document denied", True)
        assert permission == "write"

    def add_comment(self, comment_type, text):
        comments.append((comment_type, text))
        return Attr(name="COMMENT-1")


doc = Document(doctype=meta.name, name="ONE", modified="revision", meta=meta, company="ACME")
frappe.get_doc = lambda *args, **kwargs: doc
frappe.get_list = lambda *args, **kwargs: [Attr(name="ACME")]
args = {
    "doctype": meta.name,
    "name": "ONE",
    "modified": "revision",
    "company": "ACME",
    "text": "<script>x</script>\nhello",
}
assert b.write("comment", args)["name"] == "COMMENT-1"
assert comments == [("Comment", "&lt;script&gt;x&lt;/script&gt;<br>hello")]
rejects(lambda: b.write("comment", dict(args, modified="old")), "changed")
doc.denied = True
rejects(lambda: b.write("comment", args), "denied")
assert len(comments) == 1
# Exercise the public proposal and browser confirmation path, not only write().
doc.denied = False
comment_permissions.clear()
frappe.get_doc = (
    lambda *values, **kwargs: ns["Record"](values[0]) if isinstance(values[0], dict) else doc
)
proposal = b.execute("comment", args, "public-comment-request")
assert proposal["approval_required"] and len(comments) == 1
assert comment_permissions == ["write"]
doc.denied = True
rejects(lambda: b.confirm(proposal["proposal_id"]), "denied")
assert len(comments) == 1
assert comment_permissions == ["write", "write"]
doc.denied = False
assert b.confirm(proposal["proposal_id"])["name"] == "COMMENT-1"
assert len(comments) == 2 and comment_permissions == ["write", "write", "write"]
assert b.confirm(proposal["proposal_id"])["name"] == "COMMENT-1"
assert b.execute("comment", args, "public-comment-request")["name"] == "COMMENT-1"
assert len(comments) == 2
assert "comment" in b.WRITES and "comment" not in b.READS
assert c.coverage()["certification"] == "interface_only_module_chains_pending_qa"
assert len(c.coverage()["conversions"]) == 19
print(
    "Expanded ERP checks passed: bounded pages/CSV/aggregate/report m"
    "etadata/comment permission and version fences; conversion ledger"
    "."
)


# New native mappings reuse the same conversion permission and unsaved-draft contract.
class Source:
    doctype = "Lead"
    name = "LEAD-1"

    def check_permission(self, permission):
        assert permission == "read"


class Draft(Attr):
    def is_new(self):
        return not self.get("saved")

    def apply_fieldlevel_read_permissions(self):
        pass

    def as_dict(self):
        return dict(self)


draft = Draft(doctype="Opportunity", name=None, meta=meta)
frappe.get_attr = lambda path: lambda name: draft
frappe.is_whitelisted = lambda fn: None
original_clean = b.clean_document
b.clean_document = lambda doc: {"doctype": doc.doctype}
assert b.invoke_action(Source(), {"action": "lead.make_opportunity"})["saved"] is False
draft.saved = True
rejects(lambda: b.invoke_action(Source(), {"action": "lead.make_opportunity"}), "unsaved")
draft.saved = False
frappe.has_permission = lambda doctype, permission: not (
    doctype == "Opportunity" and permission == "create"
)
rejects(lambda: b.invoke_action(Source(), {"action": "lead.make_opportunity"}), "not explicitly")
b.clean_document = original_clean
print(
    "Native conversion contract passed: unsaved draft, target-create "
    "denial and saved-target rejection."
)
