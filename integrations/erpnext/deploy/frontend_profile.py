"""Pure versioned browser contracts. Native Cloud remains the publishing authority."""
from copy import deepcopy


def text(limit=140, minimum=1):
    return {"type": "string", "minLength": minimum, "maxLength": limit}


def object_schema(properties, required):
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def array(items, limit, minimum=0):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": limit}


def definition(revision=1):
    if type(revision) is not int or revision not in {1, 2}:
        raise ValueError("Only frontend revisions 1 and 2 are defined")
    if revision == 1:
        # Published v1 is immutable: retain its original schemas/descriptions/defaults.
        actions = [
            dict(name="erpnext.ui.document.open", description="Open an ERPNext document in the current user's page.",
                 risk="navigation", parameters={"type": "object", "properties": {
                     "doctype": {"type": "string"}, "name": {"type": "string"}},
                     "required": ["doctype", "name"], "additionalProperties": False}),
            dict(name="erpnext.ui.form.fill", description="Fill editable fields on the exact currently open legacy Frappe form without saving. Requires matching route, DocType and document name.",
                 risk="local_state", parameters={"type": "object", "properties": {
                     "route": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                     "doctype": {"type": "string"}, "name": {"type": "string"}, "values": {"type": "object"}},
                     "required": ["route", "doctype", "name", "values"], "additionalProperties": False}),
        ]
        return dict(frontend_app_id="erpnext-web", revision=1,
                    readables=[dict(name="erpnext.ui.context")], actions=actions)

    route = array(text(), 8, 1)
    context = object_schema({"route": route, "doctype": text(), "name": text(),
        "modified": text(minimum=0), "draft_digest": text(64, 64), "company": text(),
        "controller_instance": text(), "load_generation": {"type": "integer", "minimum": 0},
        "filter_digest": text(64, 64)}, ["route"])
    form = deepcopy(context)
    form["required"] = ["route", "doctype", "name", "modified", "draft_digest"]
    # ponytail: the deployed schema has no unions or dynamic maps and depth <=4.
    # Handlers enforce kind/exactly-one slot, finite numbers and metadata field authority.
    scalar = {"kind": {"type": "string", "enum": ["text", "number", "boolean", "null"]},
              "text": text(10000, 0), "number": {"type": "number"}, "boolean": {"type": "boolean"}}
    cell = object_schema(dict(field=text(), **scalar), ["field", "kind"])
    filter_value = dict(scalar, kind={"type": "string", "enum": ["text", "number", "boolean", "null", "texts", "numbers", "booleans"]},
                        texts=array(text(10000, 0), 100, 1), numbers=array({"type": "number"}, 100, 1), booleans=array({"type": "boolean"}, 100, 1))
    filters = array(object_schema(dict(field=text(), operator={"type": "string", "enum": ["=", "!=", ">", "<", ">=", "<=", "like", "not like", "in", "not in", "between", "is"]}, **filter_value), ["field", "operator", "kind"]), 20)
    report_filters = array(cell, 20)
    navigation_result = object_schema({"context": context, "opened": {"type": "boolean"},
        "state": {"type": "string", "enum": ["loaded", "pending"]}}, ["context", "opened", "state"])
    list_result = deepcopy(navigation_result)
    list_result["properties"]["complete"] = {"type": "boolean", "enum": [False]}
    list_result["required"].append("complete")
    draft_result = object_schema({"context": context, "saved": {"type": "boolean", "enum": [False]}}, ["context", "saved"])
    patch_result = object_schema({"context": context, "saved": {"type": "boolean", "enum": [False]},
        "partial": {"type": "boolean"}, "changed": array(object_schema({"name": text(), "field": text()}, ["name", "field"]), 100),
        "created": array(object_schema({"row_key": text(), "name": text()}, ["row_key", "name"]), 50)}, ["context", "saved", "partial", "changed", "created"])
    read_result = object_schema({"context": context, "scope": {"type": "string", "enum": ["form", "list", "report", "metadata"]},
        "company": text(), "controller_instance": text(), "load_generation": {"type": "integer", "minimum": 0},
        "filter_digest": text(64, 64), "complete": {"type": "boolean"},
        "reason": text(1000, 0), "columns": array(object_schema({"field": text(), "label": text(500, 0)}, ["field", "label"]), 30),
        "cells": array(object_schema(dict(row=text(), table=text(minimum=0), field=text(), **scalar), ["row", "table", "field", "kind"]), 1000),
        "pages": array(object_schema({"field": text(minimum=0), "start": {"type": "integer", "minimum": 0, "maximum": 10000},
            "next_start": {"type": "integer", "minimum": -1, "maximum": 10050}, "has_more": {"type": "boolean"}}, ["field", "start", "next_start", "has_more"]), 10)},
        ["context", "scope", "company", "complete", "cells", "pages"])

    def action(name, description, risk, parameters, result):
        return dict(name="erpnext.ui." + name, description=description, risk=risk,
                    parameters=parameters, result_schema=result, max_result_bytes=16384)

    actions = [
        action("document.open", "Open a permitted saved document from the exact expected page.", "navigation",
               object_schema({"expected": context, "doctype": text(), "name": text()}, ["expected", "doctype", "name"]), navigation_result),
        action("list.open", "Open the native List view with bounded permission-checked scalar filters.", "navigation",
               object_schema({"expected": context, "doctype": text(), "filters": filters}, ["expected", "doctype"]), list_result),
        action("report.open", "Open a source-reviewed native report with bounded typed filters; pending is not completed execution.", "navigation",
               object_schema({"expected": context, "report": text(), "filters": report_filters}, ["expected", "report"]), navigation_result),
        action("document.new", "Open a full-form local draft using native defaults without Quick Entry or saving.", "local_state",
               object_schema({"expected": context, "doctype": text()}, ["expected", "doctype"]), draft_result),
        action("page.read", "Read explicit permitted page fields; list/report rows require a current completed-load/company/output contract, otherwise metadata only.", "presentation",
               object_schema({"expected": context, "fields": array(text(), 30, 1), "tables": array(object_schema({"field": text(), "fields": array(text(), 20, 1),
                   "start": {"type": "integer", "minimum": 0, "maximum": 10000}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}}, ["field", "fields", "start", "limit"]), 10)}, ["expected"]), read_result),
        action("form.fill", "Fill typed scalar cells on the exact draft identity, version and local digest; validate every cell before native setters; never save.", "local_state",
               object_schema({"expected": form, "values": array(cell, 30, 1)}, ["expected", "values"]), patch_result),
        action("form.children.patch", "Patch or append typed child cells: at most 100 TOTAL cells across updates and append, 50 rows and 20 fields per row. Before mutation validate ownership and the COMPLETE serialized result budget <=16384 bytes, including context and created row identities; reject overflow. Never save.", "local_state",
               object_schema({"expected": form, "field": text(),
                   "updates": array(object_schema(dict(name=text(), field=text(), **scalar), ["name", "field", "kind"]), 100),
                   "append": array(object_schema(dict(row_key=text(), field=text(), **scalar), ["row_key", "field", "kind"]), 100)}, ["expected", "field"]), patch_result),
    ]
    return dict(frontend_app_id="erpnext-web", revision=2,
                readables=[dict(name="erpnext.ui.context", state_schema=context, max_state_bytes=16384)], actions=actions)


def install_profile(service, registry, profile, *, rebind=False, namespace="erpnext"):
    """Publish immutable content; replacing an existing Host binding is an explicit CAS."""
    binding = service.get_binding_for_host(host_app_id="erpnext", namespace_id=namespace, frontend_app_id="erpnext-web")
    mismatch = binding and (binding.revision != profile.revision or binding.profile_digest != profile.profile_digest)
    if mismatch and not rebind:
        raise ValueError("Existing frontend binding differs; use --rebind-frontend-profile deliberately")
    published = registry.get_profile("erpnext-web", profile.revision)
    if published and published.profile_digest != profile.profile_digest:
        raise ValueError("Published frontend revision has different content")
    if not published:
        service.publish(profile)
    if not binding or mismatch:
        service.bind(host_app_id="erpnext", namespace_id=namespace, frontend_app_id="erpnext-web",
                     revision=profile.revision, profile_digest=profile.profile_digest,
                     expected_binding_revision=binding.binding_revision if binding else 0)


def validate_patch_cell_budget(parameters):
    """Semantic contract oracle; browser handlers must apply this before mutation.

    Native restricted JSON Schema cannot sum separate array lengths. Each array is
    bounded by schema; the combined bound keeps changed receipts representable.
    Full serialized receipt size (context and created IDs included) is a separate
    mandatory handler preflight, since a count bound alone cannot prove byte size.
    """
    if len(parameters.get("updates", [])) + len(parameters.get("append", [])) > 100:
        raise ValueError("Child patch exceeds 100 total cells")
