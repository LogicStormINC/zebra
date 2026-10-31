"""Operator-run native File/HTTP check. main() creates and removes only UUID QA data.

Run in initialized Frappe: import runpy; runpy.run_path(PATH)['main']()
Cloud history is patched in this process only; no Task, model or business execution.
"""

import json
import re
import secrets
import time
import uuid

import frappe
import requests

from zebra_erpnext import chat, history, presentation


def main():
    marker = "ZEBRA-REPORT-QA-" + uuid.uuid4().hex
    user = marker.lower() + "@example.invalid"
    password = secrets.token_urlsafe(24)
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    other = marker + "-Company"
    conversation = permission = employee = None
    original = history.load
    passed = []
    try:
        frappe.set_user("Administrator")
        frappe.get_doc(
            dict(
                doctype="Company",
                name=other,
                company_name=other,
                abbr="QRP",
                default_currency="CNY",
                country="China",
            )
        ).db_insert()
        frappe.get_doc(
            dict(
                doctype="User",
                email=user,
                first_name=marker,
                enabled=1,
                new_password=password,
                send_welcome_email=0,
                user_type="System User",
                roles=[{"role": "Employee"}],
            )
        ).insert(ignore_permissions=True)
        # ERPNext removes Employee from Users without a mapped Employee row.
        # ponytail: this UUID permission fixture needs no Employee workflow or
        # naming-series allocation; delete its isolated mapping in finally.
        employee = marker
        frappe.get_doc(
            dict(
                doctype="Employee",
                name=employee,
                first_name=marker,
                employee_name=marker,
                company=company,
                user_id=user,
                status="Active",
            )
        ).db_insert()
        frappe.get_doc("User", user).add_roles("Employee")
        permission = (
            frappe.get_doc(
                dict(
                    doctype="User Permission",
                    user=user,
                    allow="Company",
                    for_value=company,
                    apply_to_all_doctypes=1,
                )
            )
            .insert(ignore_permissions=True)
            .name
        )
        frappe.db.commit()
        frappe.clear_cache(user=user)
        frappe.set_user(user)
        assert frappe.get_all(
            "Has Role", filters={"parenttype": "User", "parent": user}, pluck="role"
        ) == ["Employee"]
        assert "Employee" in frappe.get_roles()
        conversation = chat.create(marker, company)["name"]
        frappe.db.set_value("Zebra Conversation", conversation, "task_id", "qa-public-history-only")
        frappe.db.commit()
        events = [
            dict(
                event_id=marker + "-u",
                event_type="user_message_received",
                payload={"content": "QA text only"},
            ),
            dict(
                event_id=marker + "-a",
                event_type="answer_committed",
                payload={"assistant_message": "# QA public report\n\nOnly isolated test content."},
            ),
        ]
        history.load = lambda doc: ({"status": "completed"}, events)
        message = history.messages(events)[-1]
        args = (conversation, message["id"], message["digest"])
        original_commit = frappe.db.commit
        commit_checks = []

        def protected_commit():
            rows = frappe.get_all(
                "File",
                filters={
                    "attached_to_doctype": "Zebra Conversation",
                    "attached_to_name": conversation,
                },
                fields=["owner", "is_private"],
            )
            assert all(row.owner == "Administrator" and row.is_private for row in rows), (
                "File hooks committed an unprotected report"
            )
            commit_checks.append(len(rows))
            return original_commit()

        frappe.db.commit = protected_commit
        try:
            first = presentation.save(*args, report=True)
            second = presentation.save(*args, report=True)
        finally:
            frappe.db.commit = original_commit
        assert commit_checks == [1, 1], ("Unexpected intermediate File hook commit", commit_checks)
        assert first == second and first["report_saved"]
        file_rows = frappe.get_all(
            "File",
            filters={"attached_to_doctype": "Zebra Conversation", "attached_to_name": conversation},
            fields=["name", "owner", "is_private", "file_url"],
        )
        assert (
            len(file_rows) == 1
            and file_rows[0].owner == "Administrator"
            and file_rows[0].is_private
        )
        assert presentation.save(*args, feedback="helpful")["feedback"] == "helpful"
        downloaded = presentation.download(*args)
        assert "Only isolated test content." in (
            downloaded.decode("utf-8") if isinstance(downloaded, bytes) else downloaded
        )
        assert "file_url" not in json.dumps(first) and "report_file" not in first
        passed.append(
            "native private service-owned File; double save idempotency; feed"
            "back; same-source report body"
        )
        config = frappe.conf.zebra_agent
        session = requests.Session()
        session.verify = config["ca_file"]
        base = config["origin"]
        login = session.post(
            base + "/api/method/login", json={"usr": user, "pwd": password}, timeout=30
        )
        login.raise_for_status()
        page = session.get(base + "/app", timeout=30)
        page.raise_for_status()
        token = re.search(r'frappe\.csrf_token\s*=\s*[\'"]([^\'"]+)', page.text).group(1)
        session.headers["X-Frappe-CSRF-Token"] = token
        params = {
            "conversation": conversation,
            "message_id": message["id"],
            "digest": message["digest"],
        }
        response = session.get(
            base + "/api/method/zebra_erpnext.api.report_download", params=params, timeout=30
        )
        assert (
            response.status_code == 200
            and response.headers["Content-Type"].startswith("application/octet-stream")
            and b"Only isolated test content." in response.content
        )
        raw = session.get(base + file_rows[0].file_url, timeout=30)
        native = session.get(
            base + "/api/method/frappe.client.get",
            params={"doctype": "File", "name": file_rows[0].name},
            timeout=30,
        )
        assert raw.status_code == 403 and native.status_code == 403, (
            "native File bypass",
            raw.status_code,
            native.status_code,
        )
        passed.append("same-company fixed RPC allowed; raw private URL and native File API denied")
        frappe.set_user("Administrator")
        frappe.db.set_value("User Permission", permission, "for_value", other)
        frappe.db.commit()
        frappe.clear_cache(user=user)
        denied = session.get(
            base + "/api/method/zebra_erpnext.api.report_download", params=params, timeout=30
        )
        assert denied.status_code == 403, ("company revocation", denied.status_code)
        passed.append("company revocation denied existing report retrieval")
        print(
            json.dumps(
                {
                    "passed": passed,
                    "fixture_marker": marker,
                    "model_calls": 0,
                    "native_tasks_created": 0,
                },
                ensure_ascii=False,
            )
        )
    finally:
        history.load = original
        frappe.set_user("Administrator")
        if conversation:
            for file in frappe.get_all(
                "File",
                filters={
                    "attached_to_doctype": "Zebra Conversation",
                    "attached_to_name": conversation,
                },
                pluck="name",
            ):
                frappe.delete_doc("File", file, ignore_permissions=True)
            frappe.db.delete("Zebra Conversation", {"name": conversation})
        frappe.db.delete("User Permission", {"user": user})
        if employee:
            frappe.db.delete("Employee", {"name": employee, "user_id": user})
        if frappe.db.exists("Company", other):
            frappe.db.delete("Company", {"name": other})
        frappe.db.commit()
        # User insert/add_roles enqueue contact hooks; retry only this UUID
        # fixture's rolled-back cleanup, as in test_permissions_frappe.py.
        for attempt in range(3):
            try:
                if frappe.db.exists("User", user):
                    frappe.delete_doc("User", user, ignore_permissions=True)
                frappe.db.commit()
                break
            except frappe.QueryDeadlockError:
                frappe.db.rollback()
                if attempt == 2:
                    raise
                time.sleep(0.2)
