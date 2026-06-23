from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApiResponse:
    status_code: int
    body: dict[str, object]


def bad_request(reason: str) -> ApiResponse:
    return ApiResponse(
        status_code=400,
        body={
            "status": "invalid_request",
            "reason": reason,
        },
    )


def conflict(*, session_id: str, status: str, reason: str) -> ApiResponse:
    return ApiResponse(
        status_code=409,
        body={
            "session_id": session_id,
            "status": status,
            "reason": reason,
        },
    )
