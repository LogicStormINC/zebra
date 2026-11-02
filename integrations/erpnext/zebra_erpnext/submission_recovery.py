"""Pre-Task intents: definite refusal is terminal; a missing ACK remains unknown."""

import json
from uuid import UUID

import frappe

from zebra_erpnext import cloud


def _state(doc):
    return json.loads(doc.request_options or "{}").get("task_creation") or {}


def _current(doc, lock, coordinates):
    current = cloud.owned(doc.name, for_update=True, admission_lock=lock, control=True)
    if (current.request_id, current.active_run_id, current.task_id) != coordinates:
        frappe.throw("会话已变化，旧提交回执不会修改后续请求")
    return current


def _save(doc, state):
    options = json.loads(doc.request_options or "{}")
    options["task_creation"] = state
    doc.request_options = json.dumps(options, ensure_ascii=False)
    doc.db_update()
    frappe.db.commit()


def create_task(doc, payload, lock, *, first_attempt=True):
    coordinates = (doc.request_id, doc.active_run_id, doc.task_id)
    prior = _state(doc)
    uncertain = prior.get("state") in {"sending", "unknown"} or not first_attempt and not prior
    payload = prior.get("payload", payload)
    state = {"state": "sending", "uncertain_prior": uncertain, "payload": payload}
    _save(doc, state)
    try:
        result = cloud.request(
            doc,
            "POST",
            "/tasks",
            run_id=doc.active_run_id,
            key="erpnext-task-" + doc.name,
            body=payload,
            admission_lock=lock,
        )
    except Exception as error:
        current = _current(doc, lock, coordinates)
        known = (
            isinstance(error, cloud.CloudRejectedError)
            and error.status_code in {400, 401, 403, 404, 405, 413, 415, 422}
            and not uncertain
        )
        state.update(state="rejected" if known else "unknown")
        if isinstance(error, cloud.CloudRejectedError):
            state["http_status"] = error.status_code
        if known:
            current.status = "rejected"
        _save(current, state)
        raise
    current = _current(doc, lock, coordinates)
    task = str(UUID(result["task_id"]))
    revision = result.get("active_segment_sequence", result.get("current_sequence", 0))
    if type(revision) is not int or revision < 0:
        frappe.throw("任务回执版本无效，请核对原提交")
    current.task_id = task
    current.prepared_request = current.request_id
    current.prepared_revision = revision
    _save(current, {"state": "recorded", "task_id": task})
    return result


def reconcile(doc, lock):
    if doc.task_id or doc.status != "dispatching" or _state(doc).get("state") == "rejected":
        return doc
    coordinates = (doc.request_id, doc.active_run_id, doc.task_id)
    result = cloud.request(
        doc,
        "GET",
        "/task-admissions/receipt",
        run_id=doc.active_run_id,
        key="erpnext-task-" + doc.name,
        admission_lock=lock,
    )
    current = _current(doc, lock, coordinates)
    if result.get("status") == "recorded":
        task = str(UUID(result["task_id"]))
        revision = result["prepared_revision"]
        if type(revision) is not int or revision < 0:
            frappe.throw("任务回执版本无效")
        current.task_id = task
        current.prepared_request = current.request_id
        current.prepared_revision = revision
        _save(current, {"state": "recorded", "task_id": task})
    # Absence is not a proof of noncommit and never clears the original intent.
    return current


def stop_uncreated(doc, lock):
    if doc.task_id:
        return None
    if doc.status == "dispatching":
        doc = reconcile(doc, lock)
    if doc.task_id:
        return None
    if (
        doc.status in {"rejected", "cancelled"}
        and not doc.pending_command
        and _state(doc).get("state") == "rejected"
    ):
        doc.status = "cancelled"
        doc.stop_command = None
        doc.db_update()
        frappe.db.commit()
        return {"status": "cancelled", "submission_cancelled": True, "force_stop": None}
    if doc.status == "dispatching" or doc.pending_command:
        return {
            "status": "dispatching",
            "submission_cancelled": False,
            "force_stop": None,
            "requires_reconciliation": True,
        }
    return {"status": "idle", "force_stop": None}


def snapshot(doc):
    pending = doc.status == "dispatching" or bool(doc.pending_command)
    rejected = doc.status == "rejected" and not doc.pending_command
    state = {
        "phase": "reconciling"
        if pending
        else "terminal"
        if rejected or doc.status == "cancelled"
        else "idle",
        "availableActions": [],
        **(
            {"safeMessage": "创建任务的结果尚未确认；未重发原任务，请核对停止或原提交回执。"}
            if pending
            else {}
        ),
        **(
            {
                "outcome": "blocked",
                "safeMessage": "上次任务创建被明确拒绝；没有启动模型，可以修改后重新提交。",
            }
            if rejected
            else {}
        ),
    }
    return dict(
        title=doc.title if hasattr(doc, "title") else "",
        messages=[{"id": doc.request_id, "role": "user", "content": doc.pending_message}]
        if doc.pending_message
        else [],
        status="blocked" if pending else "failed" if rejected else doc.status or "idle",
        run_id=doc.active_run_id,
        run_state=state,
        clarification=None,
        rejected_request_id=doc.request_id if rejected else None,
        execution_mode=json.loads(doc.preferences_json or "{}").get("execution_mode", "standard")
        if hasattr(doc, "preferences_json")
        else "standard",
    )
