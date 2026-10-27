"""Observe an original Task-message receipt; absence never proves noncommit."""

from time import monotonic
from typing import Any

from agent_storage.postgres.task_io import task_io_deadline

from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.task_api import parse_task_id
from zebra_agent_api.task_message_contract import receipt_key, receipt_version, stored_coordinates


def read_task_message_receipt(
    app: Any, task_id: str, headers: dict[str, str] | None
) -> ApiResponse:
    parsed = parse_task_id(task_id)
    if isinstance(parsed, ApiResponse):
        return parsed
    version, key = receipt_version(headers), receipt_key(headers)
    if version is None or key is None:
        return ApiResponse(400, {"status": "invalid_request"})
    try:
        with task_io_deadline(monotonic() + 2.0):
            record = app.stores.idempotency.get(
                action=f"task-message:{task_id}", idempotency_key=key
            )
    except Exception:
        return ApiResponse(503, {"status": "unavailable"})
    if record is None:
        return ApiResponse(
            200,
            {
                "contract_version": version,
                "status": "not_observed",
                "task_id": task_id,
                "noncommit_proved": False,
            },
        )
    details: dict[str, object] = {}
    if version == 2:
        status, coordinates = stored_coordinates(record.response_body)
        details = {"coordinates_status": status, "message_coordinates": coordinates}
    return ApiResponse(
        200,
        {
            **details,
            "contract_version": version,
            "status": "recorded",
            "task_id": task_id,
            "request_hash": record.request_hash,
            "response": {"status_code": record.status_code, "body": record.response_body},
        },
    )
