"""Internal app records; ordinary users access them only through scoped RPCs."""

from pathlib import Path

import frappe


def setup():
    assets = Path(frappe.get_site_path("..", "assets", "zebra_erpnext"))
    if not assets.exists():
        assets.symlink_to(frappe.get_app_path("zebra_erpnext", "public"), target_is_directory=True)
    schemas = {
        "Zebra Conversation": [
            ("title", "Data"),
            ("user", "Link", "User"),
            ("company", "Link", "Company"),
            ("task_id", "Data"),
            ("active_run_id", "Data"),
            ("host_thread", "Data"),
            ("request_id", "Data"),
            ("preferences_json", "Long Text"),
            ("request_options", "Long Text"),
            ("pending_message", "Long Text"),
            ("prepared_request", "Data"),
            ("prepared_revision", "Int"),
            ("pending_command", "Long Text"),
            ("stop_command", "Long Text"),
            ("status", "Data"),
            ("client_surface_json", "Long Text"),
            ("presentation_json", "Long Text"),
            ("workspace_ref", "Data"),
            ("runtime_ref", "Data"),
            ("schedule_ref", "Data"),
            ("schedule_fire_id", "Data"),
        ],
        "Zebra Schedule": [
            ("title", "Data"),
            ("user", "Link", "User"),
            ("company", "Link", "Company"),
            ("conversation", "Link", "Zebra Conversation"),
            ("request_key", "Data"),
            ("native_id", "Data"),
            ("status", "Data"),
            ("runtime_ref", "Data"),
            ("body_json", "Long Text"),
            ("preferences_json", "Long Text"),
        ],
        "Zebra Knowledge": [
            ("title", "Data"),
            ("user", "Link", "User"),
            ("company", "Link", "Company"),
            ("file_id", "Link", "File"),
            ("media_type", "Data"),
            ("status", "Data"),
        ],
        "Zebra Grant": [
            ("user", "Link", "User"),
            ("company", "Link", "Company"),
            ("conversation", "Link", "Zebra Conversation"),
            ("expires_at", "Datetime"),
            ("run_id", "Data"),
            ("workspace_ref", "Data"),
            ("runtime_ref", "Data"),
        ],
        "Zebra Business Approval": [
            ("user", "Link", "User"),
            ("operation", "Data"),
            ("arguments_json", "Long Text"),
            ("request_id", "Data"),
            ("company", "Link", "Company"),
            ("digest", "Data"),
            ("expires_at", "Datetime"),
            ("status", "Select", "Pending\nCompleted"),
            ("result_json", "Long Text"),
            ("request_key", "Data"),
            ("conversation", "Link", "Zebra Conversation"),
            ("run_id", "Data"),
        ],
    }
    for name, definitions in schemas.items():
        fields = [
            dict(
                fieldname=f[0],
                label=f[0].replace("_", " ").title(),
                fieldtype=f[1],
                **({"options": f[2]} if len(f) > 2 else {}),
                **({"unique": 1} if f[0] == "request_key" else {}),
            )
            for f in definitions
        ]
        if not frappe.db.exists("DocType", name):
            frappe.get_doc(
                dict(
                    doctype="DocType",
                    name=name,
                    module="Zebra ERPNext",
                    custom=1,
                    autoname="hash",
                    fields=fields,
                    permissions=[],
                    track_changes=0,
                )
            ).insert(ignore_permissions=True)
        else:
            doc = frappe.get_doc("DocType", name)
            present = {field.fieldname for field in doc.fields}
            missing = [field for field in fields if field["fieldname"] not in present]
            if missing:
                for field in missing:
                    doc.append("fields", field)
                doc.save(ignore_permissions=True)


def prune_grants():
    frappe.db.delete("Zebra Grant", {"expires_at": ["<", frappe.utils.now_datetime()]})
