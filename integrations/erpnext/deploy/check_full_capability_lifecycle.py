"""Signed HTTP/AG-UI authority gates in the cloned site, no Worker/provider execution."""

import hashlib
import hmac
import json
import time
from pathlib import Path
from uuid import uuid4

import frappe
import requests

from zebra_erpnext import chat, cloud, runtime


def run():
    if frappe.local.site != "capability-qa.local":
        raise ValueError("cloned QA site required")
    frappe.set_user("Administrator")
    doc = cloud.owned("73okscoa80")
    if not doc.title.startswith("FULL-CAPABILITY-QA-"):
        raise ValueError("QA fixture required")
    task = cloud.request(doc, "GET", "/tasks/" + doc.task_id, run_id=doc.active_run_id)
    body = chat._run_body(doc, doc.active_run_id, task["current_sequence"], {}, None, [])
    accepted = cloud.request(
        doc,
        "POST",
        "/agui/commands",
        run_id=doc.active_run_id,
        key="qa-full-admit-" + doc.name,
        body=body,
    )
    assert (
        accepted.get("status") in {"accepted", "duplicate"} or accepted.get("accepted") is True
    ), list(accepted)
    Path("/tmp/agui-accepted.json").write_text(
        json.dumps(
            dict(
                task_id=doc.task_id,
                run_id=doc.active_run_id,
                selection=runtime.selections(doc),
                receipt=accepted,
                model_calls=0,
                search_calls=0,
            ),
            indent=2,
        )
    )
    records = frappe.get_all(
        "Zebra Schedule",
        filters={"user": "Administrator", "runtime_ref": runtime.FULL, "status": "paused"},
        fields=["name", "conversation"],
        limit_page_length=1,
    )
    if not records:
        raise ValueError("retained future-paused QA schedule required")
    from zebra_erpnext import schedules

    row = records[0]
    source = cloud.owned(row.conversation)
    record = frappe.get_doc("Zebra Schedule", row.name)
    if not record.title.startswith("Future QA"):
        raise ValueError("isolated future schedule required")
    detail = schedules.detail(source.name, record.name)
    schedules.action(source.name, record.name, "resume", detail["schedule_version"])
    settings = runtime.settings(source, cloud.config())
    fire = str(uuid4())
    request = dict(
        audience="zebra",
        threadId=record.native_id,
        runId=fire,
        scopes=[
            s
            for s in settings["scopes"]
            if s not in {"schedule.read", "schedule.manage", "extensions.manage"}
        ],
        resourceRefs=[
            {"type": "company", "id": source.company},
            {"type": "schedule_request", "id": record.name},
        ],
        principal={"userId": source.user, "workspaceId": source.workspace_ref},
    )
    timestamp = str(int(time.time()))
    digest = hashlib.sha256(
        json.dumps(request, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    headers = {
        "X-Zebra-Workload-Identity": "erpnext-scheduler-full",
        "X-Zebra-Workload-Timestamp": timestamp,
        "X-Zebra-Workload-Nonce": fire,
        "X-Zebra-Workload-Signature": hmac.new(
            settings["schedule_workload_secret"].encode(),
            f"{timestamp}\n{fire}\n{digest}".encode(),
            hashlib.sha256,
        ).hexdigest(),
    }
    session = requests.Session()
    session.verify = cloud.config()["ca_file"]
    session.trust_env = False
    uri = cloud.config()["issuer"] + "/api/method/zebra_erpnext.api.schedule_exchange"
    try:
        responses = [session.post(uri, json=request, headers=headers, timeout=15) for _ in range(2)]
        assert all(
            r.status_code == 200 and isinstance(r.json().get("grant"), str) for r in responses
        ), [r.status_code for r in responses]
        frappe.db.rollback()
        assert (
            frappe.db.count(
                "Zebra Conversation", {"schedule_ref": record.name, "schedule_fire_id": fire}
            )
            == 1
        )
        bad = session.post(
            uri,
            json=request,
            headers={**headers, "X-Zebra-Workload-Signature": "0" * 64},
            timeout=15,
        )
        assert bad.status_code in {401, 403}
    finally:
        current = schedules.detail(source.name, record.name)
        schedules.action(source.name, record.name, "pause", current["schedule_version"])
    paused = session.post(uri, json=request, headers=headers, timeout=15)
    assert paused.status_code in {401, 403}, paused.status_code
    proof = dict(
        stage="actual_signed_schedule_exchange",
        valid_requests=2,
        same_firing_conversations=1,
        bad_signature_denied=True,
        paused_firing_denied=True,
        scheduler_started=False,
        model_calls=0,
        search_calls=0,
    )
    Path("/tmp/schedule-authority-gate.json").write_text(json.dumps(proof, indent=2))
    print(json.dumps(dict(agui_admitted=True, **proof)))
