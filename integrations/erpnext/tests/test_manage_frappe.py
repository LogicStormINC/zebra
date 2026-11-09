"""Operator-run main() in initialized Frappe; two connections, UUID metadata only.
No native Task, model, File or business operation. Removes its own Conversation.
"""

import json
import threading
import uuid

import frappe

from zebra_erpnext import chat, cloud


def main():
    frappe.set_user("Administrator")
    marker = "ZEBRA-MANAGE-QA-" + uuid.uuid4().hex
    site, sites_path = frappe.local.site, frappe.local.sites_path
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    conversation = None
    passed = []

    def other_connection(values):
        errors = []

        def update():
            try:
                frappe.init(site=site, sites_path=sites_path)
                frappe.connect()
                frappe.set_user("Administrator")
                with frappe.cache.lock(
                    "zebra:submit:" + conversation, timeout=30, blocking_timeout=5
                ):
                    frappe.db.set_value(
                        "Zebra Conversation", conversation, values, update_modified=False
                    )
                    frappe.db.commit()
            except Exception as error:
                errors.append(error)
            finally:
                frappe.destroy()

        thread = threading.Thread(target=update)
        thread.start()
        thread.join(20)
        assert not thread.is_alive(), "Independent metadata transaction timed out"
        if errors:
            raise errors[0]

    try:
        conversation = chat.create(marker, company)["name"]
        frappe.db.commit()
        old = cloud.owned(conversation).presentation_json
        current = json.dumps(
            {
                "qa": {
                    "message_id": "qa",
                    "feedback": "helpful",
                    "report_file": "qa-opaque-reference",
                }
            }
        )
        other_connection({"presentation_json": current})
        assert cloud.owned(conversation).presentation_json == old, (
            "Did not retain a genuine RR snapshot"
        )
        original_commit = frappe.db.commit
        commits = []

        def in_lock_commit():
            assert frappe.cache.lock("zebra:submit:" + conversation).locked(), (
                "Management released admission before commit"
            )
            commits.append(True)
            return original_commit()

        frappe.db.commit = in_lock_commit
        try:
            try:
                result = chat.manage(conversation, title=marker + " renamed")
            except frappe.QueryDeadlockError:
                # MariaDB innodb_snapshot_isolation=ON rejects current reads
                # against an older RR snapshot. Model a failed HTTP request's
                # rollback, then an explicit new request; never retry in product.
                assert not commits
                frappe.db.rollback()
                assert (
                    frappe.db.get_value("Zebra Conversation", conversation, "presentation_json")
                    == current
                )
                frappe.db.rollback()
                passed.append(
                    "old RR current-read conflict rolled back without losing newer presentation"
                )
                result = chat.manage(conversation, title=marker + " renamed")
            assert result["title"] == marker + " renamed"
        finally:
            frappe.db.commit = original_commit
        assert commits == [True]
        assert (
            frappe.db.get_value("Zebra Conversation", conversation, "presentation_json") == current
        )
        passed.append(
            "two-connection RR stale snapshot rename preserves committed pres"
            "entation and commits inside admission"
        )
        assert cloud.owned(conversation).status == "idle"
        other_connection({"status": "dispatching", "pending_command": "qa pending command"})
        assert cloud.owned(conversation).status == "idle", (
            "Did not retain a stale admission snapshot"
        )
        try:
            chat.manage(conversation, delete=True)
        except (frappe.ValidationError, frappe.QueryDeadlockError):
            pass
        else:
            raise AssertionError("Stale snapshot deleted a currently dispatching conversation")
        frappe.db.rollback()
        assert frappe.db.get_value("Zebra Conversation", conversation, "status") == "dispatching"
        assert (
            frappe.db.get_value("Zebra Conversation", conversation, "presentation_json") == current
        )
        try:
            chat.manage(conversation, delete=True)
        except frappe.ValidationError:
            pass
        else:
            raise AssertionError("Fresh current read allowed pending dispatch deletion")
        frappe.db.rollback()
        passed.append("current locked read rejects deletion after independent pending dispatch")
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
        frappe.db.rollback()
        if conversation:
            frappe.db.delete("Zebra Conversation", {"name": conversation})
        frappe.db.commit()
