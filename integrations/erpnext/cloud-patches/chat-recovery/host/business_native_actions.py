"""Published native business actions and unsaved conversion drafts."""

import inspect

import frappe

from zebra_erpnext.capabilities import published_actions


def invoke_action(doc, args, persist=False):
    from zebra_erpnext import business

    entry = published_actions(doc.doctype).get(args["action"])
    if not entry:
        business.fail("Business action is not explicitly published", True)
    doc.check_permission(entry["permission"])
    parameters = args.get("parameters", {})
    schema = entry.get("parameters", {})
    if (
        not isinstance(parameters, dict)
        or not isinstance(schema, dict)
        or parameters.keys() != schema.keys()
    ):
        business.fail("Action parameters must exactly match the published schema")
    types = {"str": str, "int": int, "float": float, "bool": bool}
    for key, expected in schema.items():
        if (
            key in business.FORBIDDEN | business.SYSTEM_FIELDS
            or key.startswith("_")
            or expected not in types
            or type(parameters[key]) is not types[expected]
        ):
            business.fail("Invalid business action parameter: " + key)
    if entry.get("conversion"):
        function = frappe.get_attr(entry["conversion"])
        frappe.is_whitelisted(function)
        target = entry["target_doctype"]
        if not frappe.has_permission(target, "create") or not frappe.has_permission(target, "read"):
            business.fail("Conversion target is not accessible", True)
        draft = (
            function(doc.doctype, doc.name)
            if args["action"].endswith(".make_payment_entry")
            else function(doc.name)
        )
        if draft.doctype != target or not draft.is_new():
            business.fail("Business conversion must return an unsaved target draft")
        business.check_company(draft, args.get("company"))
        if persist:
            draft.insert()
            business.check_company(draft, args.get("company"))
            return {"saved": True, "target_doctype": target, "document": business.serialized(draft)}
        draft.apply_fieldlevel_read_permissions()
        return {
            "saved": False,
            "target_doctype": target,
            "document": business.clean_document(draft),
        }
    if persist:
        business.fail("Only reviewed native conversions may create mapped drafts", True)
    method_name = entry.get("method", "")
    if not method_name.isidentifier() or method_name.startswith("_"):
        business.fail("Invalid published controller method")
    method = getattr(doc, method_name, None)
    if not callable(method):
        business.fail("Published action method does not exist")
    function = getattr(method, "__func__", method)
    frappe.is_whitelisted(function)
    if "POST" not in frappe.allowed_http_methods_for_whitelisted_func.get(function, ()):
        business.fail("Published action does not allow POST", True)
    inspect.signature(method).bind(**parameters)
    # Only deployer-published controller actions, all confirmed, with native document checks.
    return method(**parameters)
