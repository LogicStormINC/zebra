"""Bounded HTTP event cursor parsing shared by stream routes."""

from fastapi import Request
from fastapi.responses import JSONResponse


def after_sequence(request: Request) -> tuple[int, JSONResponse | None]:
    raw = request.query_params.get("after_sequence")
    if raw is None:
        return -1, None
    try:
        value = int(raw)
    except ValueError:
        value = -2
    if value < -1:
        return -1, JSONResponse(
            status_code=400,
            content={
                "status": "invalid_request",
                "reason": "after_sequence must be an integer greater than or equal to -1",
            },
        )
    return value, None
