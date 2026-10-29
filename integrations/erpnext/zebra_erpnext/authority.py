"""Fixed, read-only Worker control probe; deliberately absent from the manifest."""
import hashlib
import json
from datetime import timezone

import frappe
from frappe.utils import get_datetime, now_datetime

from zebra_erpnext import cloud


FIELDS = {"task_id", "thread_id", "run_id", "principal", "workspace_ref", "expires_at"}


def check(record, args):
    if (not isinstance(args, dict) or set(args) != FIELDS
            or any(not isinstance(value, str) or not 0 < len(value) <= 512 for value in args.values())):
        frappe.throw("Invalid authority probe", frappe.PermissionError)
    conversation = cloud.owned(record.conversation)
    cloud.require_admission_open()
    from zebra_erpnext.schedule_authority import bind_execution
    conversation = bind_execution(conversation, record, args)
    expected = dict(task_id=conversation.task_id, thread_id=conversation.host_thread,
                    run_id=record.run_id, principal=record.user, workspace_ref=record.workspace_ref)
    if (any(args[key] != value for key, value in expected.items())
            or conversation.user != record.user or conversation.company != record.company
            or conversation.workspace_ref != record.workspace_ref
            or not record.run_id or conversation.active_run_id != record.run_id
            or conversation.status not in {"dispatching", "running"}):
        frappe.throw("Execution authority revoked", frappe.PermissionError)
    # Frappe stores local naive datetimes; compare in its native timezone first.
    from frappe.utils import get_system_timezone
    from zoneinfo import ZoneInfo

    frozen = get_datetime(args["expires_at"])
    if frozen.tzinfo is None:
        frappe.throw("Authority expiry must carry a timezone", frappe.PermissionError)
    frozen_local = frozen.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)
    expiry = min(get_datetime(record.expires_at), frozen_local)
    if expiry <= now_datetime():
        frappe.throw("Execution authority expired", frappe.PermissionError)
    identity = {**expected, "company": record.company}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return dict(decision="allowed", identity=identity, metadata_digest=digest,
                expires_at=expiry.replace(tzinfo=ZoneInfo(get_system_timezone())).astimezone(timezone.utc).isoformat())
