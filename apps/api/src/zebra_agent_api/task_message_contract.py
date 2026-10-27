"""Explicit Task-message receipt negotiation and stored source-coordinate validation."""

from uuid import UUID

RECEIPT_VERSION_HEADER = "X-Zebra-Task-Message-Receipt-Version"


def receipt_version(headers: dict[str, str] | None) -> int | None:
    value = next(
        (
            v.strip()
            for k, v in (headers or {}).items()
            if k.lower() == RECEIPT_VERSION_HEADER.lower()
        ),
        "1",
    )
    return {"1": 1, "2": 2}.get(value)


def valid_receipt_key(key: str | None) -> bool:
    return key is not None and 1 <= len(key) <= 128 and all(33 <= ord(c) <= 126 for c in key)


def receipt_key(headers: dict[str, str] | None) -> str | None:
    key = next(
        (v.strip() for k, v in (headers or {}).items() if k.lower() == "idempotency-key"), ""
    )
    return key if valid_receipt_key(key) else None


def stored_coordinates(body: dict[str, object]) -> tuple[str, dict[str, object] | None]:
    if "message_coordinates" not in body:
        return "not_recorded", None
    value = body["message_coordinates"]
    if not isinstance(value, dict) or set(value) != {"event_id", "segment_id", "segment_sequence"}:
        return "invalid", None
    for name in ("event_id", "segment_id"):
        raw = value[name]
        try:
            if not isinstance(raw, str) or str(UUID(raw)) != raw:
                return "invalid", None
        except ValueError:
            return "invalid", None
    sequence = value["segment_sequence"]
    if (
        type(sequence) is not int
        or sequence < 0
        or type(body.get("sequence")) is not int
        or body["sequence"] != sequence
        or type(body.get("current_sequence")) is not int
        or body["current_sequence"] != sequence
    ):
        return "invalid", None
    return "recorded", dict(value)
