"""Operator-run native Frappe + HTTP permission check; removes its own UUID fixtures."""

import json
import re
import secrets
import time
import uuid

import frappe
import requests

from zebra_erpnext import business, chat, cloud


def main():
    marker = "ZEBRA-PERM-QA-" + uuid.uuid4().hex
    user, password = marker.lower() + "@example.invalid", secrets.token_urlsafe(24)
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    other = marker + "-Company"
    todo = proposal = conversation = employee = None
    passed = []
    try:
        frappe.set_user("Administrator")
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
        # ERPNext strips Employee unless a mapped Employee exists. This UUID
        # permission row avoids Employee business workflows/naming-series writes.
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
        # A bare, isolated Company row is enough for a scope test; no charts,
        # accounts or warehouses are generated and no business company is edited.
        frappe.get_doc(
            dict(
                doctype="Company",
                name=other,
                company_name=other,
                abbr="QAX",
                default_currency="CNY",
                country="China",
            )
        ).db_insert()
        todo = (
            frappe.get_doc(
                dict(
                    doctype="ToDo",
                    description=marker,
                    allocated_to="Administrator",
                    assigned_by="Administrator",
                )
            )
            .insert()
            .name
        )
        proposal = business.execute(
            "create",
            dict(doctype="ToDo", values={"description": marker + " approval"}, company=company),
            marker,
        )["proposal_id"]
        conversation = chat.create(marker, company)["name"]
        frappe.db.set_value("Zebra Business Approval", proposal, "conversation", conversation)
        frappe.db.commit()
        frappe.clear_cache(user=user)
        assert "Employee" in frappe.get_roles(user)
        config = frappe.conf.zebra_agent
        session = requests.Session()
        session.verify = config["ca_file"]
        base = config["origin"]
        r = session.post(
            base + "/api/method/login", json={"usr": user, "pwd": password}, timeout=30
        )
        r.raise_for_status()
        page = session.get(base + "/app", timeout=30)
        page.raise_for_status()
        token = re.search(r'frappe\.csrf_token\s*=\s*[\'"]([^\'"]+)', page.text).group(1)
        session.headers["X-Frappe-CSRF-Token"] = token

        def rpc(method, body):
            return session.post(base + "/api/method/zebra_erpnext." + method, json=body, timeout=30)

        r = rpc("api.bootstrap", {})
        r.raise_for_status()
        assert company in r.json()["message"]["companies"]
        passed.append("ordinary Employee session and allowed company")
        checks = [
            ("foreign settings read", "api.conversation_settings", {"conversation": conversation}),
            (
                "foreign settings write",
                "api.save_conversation_settings",
                {
                    "conversation": conversation,
                    "model_profile": "deepseek-v4-pro-executor-v1",
                    "reasoning_effort": "max",
                },
            ),
            (
                "foreign rename",
                "api.rename_conversation",
                {"conversation": conversation, "title": "unauthorized"},
            ),
            ("foreign delete", "api.delete_conversation", {"conversation": conversation}),
            ("foreign conversation snapshot", "api.snapshot", {"conversation": conversation}),
            (
                "foreign capability catalog",
                "api.capability_catalog",
                {"conversation": conversation},
            ),
            ("foreign usage", "api.task_usage", {"conversation": conversation}),
            ("foreign artifacts", "api.task_artifacts", {"conversation": conversation}),
            ("foreign attachments", "api.task_attachments", {"conversation": conversation}),
            (
                "foreign artifact detail",
                "api.artifact_detail",
                {"conversation": conversation, "artifact_id": "foreign"},
            ),
            (
                "foreign artifact content",
                "api.artifact_content",
                {"conversation": conversation, "artifact_id": "foreign"},
            ),
            (
                "foreign report save",
                "api.save_report",
                {"conversation": conversation, "message_id": "foreign", "digest": "0" * 64},
            ),
            (
                "foreign answer feedback",
                "api.answer_feedback",
                {
                    "conversation": conversation,
                    "message_id": "foreign",
                    "digest": "0" * 64,
                    "feedback": "helpful",
                },
            ),
            (
                "foreign browser proxy",
                "api.client_proxy",
                dict(conversation=conversation, path="/v1/unknown", method="GET"),
            ),
            ("foreign business approval", "business.confirm", {"proposal_id": proposal}),
            (
                "private ToDo native document permission",
                "business.execute",
                dict(
                    operation="get",
                    arguments={"doctype": "ToDo", "name": todo, "company": company},
                    request_id=marker + "-get",
                ),
            ),
            (
                "company target outside selected company",
                "business.execute",
                dict(
                    operation="get",
                    arguments={"doctype": "Company", "name": other, "company": company},
                    request_id=marker + "-scope",
                ),
            ),
        ]
        for label, method, body in checks:
            r = rpc(method, body)
            assert r.status_code == 403, (label, r.status_code, r.text[:120])
            passed.append(label + " denied")
        for method, args in [
            ("artifact_preview", {"artifact_id": "foreign"}),
            ("artifact_download", {"artifact_id": "foreign"}),
            ("report_download", {"message_id": "foreign", "digest": "0" * 64}),
        ]:
            r = session.get(
                base + "/api/method/zebra_erpnext.api." + method,
                params={"conversation": conversation, **args},
                timeout=30,
            )
            assert r.status_code == 403, (method, r.status_code, r.text[:120])
            passed.append("foreign " + method + " denied")
        assert not frappe.db.exists("ToDo", {"description": marker + " approval"})
        passed.append("denied approval produced no mutation")
        frappe.db.commit()  # end the CLI's HTTP-era read snapshot before native requests
        assert chat.manage(conversation, title="  metadata QA  ")["title"] == "metadata QA"
        frappe.db.commit()  # model the next independent HTTP request's transaction
        assert chat.manage(conversation, delete=True)["deleted"]
        assert not any(row.name == conversation for row in chat.conversations())
        try:
            cloud.owned(conversation)
        except frappe.PermissionError:
            pass
        else:
            raise AssertionError("Deleted conversation remains accessible")
        from frappe.utils import get_datetime, now_datetime

        assert (
            get_datetime(frappe.db.get_value("Zebra Business Approval", proposal, "expires_at"))
            <= now_datetime()
        )
        assert not frappe.db.exists("ToDo", {"description": marker + " approval"})
        passed.append(
            "deleted mapping hidden and denied; pending approval revoked without business mutation"
        )
        print(json.dumps({"passed": passed, "fixture_marker": marker}, ensure_ascii=False))
    finally:
        frappe.set_user("Administrator")
        if conversation:
            frappe.db.delete("Zebra Conversation", {"name": conversation})
        if proposal:
            frappe.db.delete("Zebra Business Approval", {"name": proposal})
        if todo and frappe.db.exists("ToDo", todo):
            frappe.delete_doc("ToDo", todo, ignore_permissions=True)
        if employee:
            frappe.db.delete("Employee", {"name": employee, "user_id": user})
        if frappe.db.exists("Company", other):
            frappe.db.delete("Company", {"name": other})
        frappe.db.commit()  # release HTTP-era read snapshots before native User hooks
        # Frappe's async create_contact job may commit during native User.on_trash.
        # Retry only this disposable user's rolled-back cleanup transaction.
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


if __name__ == "__main__":
    frappe.init(site="192.168.110.42", sites_path="/home/frappe/frappe-bench/sites")
    frappe.connect()
    try:
        main()
    finally:
        frappe.destroy()
