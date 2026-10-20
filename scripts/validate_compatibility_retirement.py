"""Offline compatibility planning check; never authorizes deletion or live cutover."""

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

COMPATIBILITY = {
    "trench_messages",
    "host_binding_legacy",
    "schedule_exchange_legacy",
    "coverage_v1",
}
IMAGE = re.compile(r"^sha256:[0-9a-f]{64}$")
MAX_BYTES = 1_048_576


def _load(path: Path) -> dict:
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError("retirement document exceeds size limit")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate retirement document key")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("retirement document must be an object")
    return value


def _artifact(base: Path, reference: object) -> dict:
    if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
        raise ValueError("missing digest-bound evidence")
    if not isinstance(reference["path"], str) or not reference["path"].strip():
        raise ValueError("missing evidence path")
    path = base / reference["path"]
    if not isinstance(reference["sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", reference["sha256"]
    ):
        raise ValueError("invalid evidence digest")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("evidence exceeds size limit")
    if hashlib.sha256(path.read_bytes()).hexdigest() != reference["sha256"]:
        raise ValueError("evidence digest mismatch")
    return _load(path)


def _task_ids(value: object) -> set[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() or len(item) > 256 for item in value
    ):
        raise ValueError("inventory requires explicit pending task IDs")
    if len(set(value)) != len(value):
        raise ValueError("duplicate inventory task ID")
    return set(value)


def validate(path: Path, *, now: datetime | None = None) -> dict:
    """Check supplied material only. No DB, broker, registry or deployment access."""
    plan = _load(path)
    if type(plan.get("schema_version")) is not int or plan["schema_version"] != 1:
        raise ValueError("unsupported retirement plan schema")
    namespace = plan.get("deployment_namespace")
    if not isinstance(namespace, str) or not namespace.strip() or len(namespace) > 128:
        raise ValueError("missing retirement namespace")
    selected = plan.get("compatibility")
    if (
        not isinstance(selected, list)
        or not selected
        or any(not isinstance(item, str) or item not in COMPATIBILITY for item in selected)
        or len(set(selected)) != len(selected)
    ):
        raise ValueError("invalid explicit compatibility selection")
    if plan.get("historical_decoder") != "retain":
        raise ValueError("historical decoding must remain available")
    inventory = _artifact(path.parent, plan.get("inventory"))
    if inventory.get("deployment_namespace") != namespace:
        raise ValueError("inventory namespace mismatch")
    if inventory.get("compatibility") != selected:
        raise ValueError("inventory must bind the exact compatibility selection")
    try:
        observed = datetime.fromisoformat(inventory["observed_at"].replace("Z", "+00:00"))
    except (KeyError, TypeError, AttributeError, ValueError):
        raise ValueError("missing inventory observation time") from None
    current = now or datetime.now(UTC)
    if observed.tzinfo is None or not timedelta(0) <= current - observed <= timedelta(hours=24):
        raise ValueError("inventory must be current, timezone-aware and not from the future")
    if not isinstance(inventory.get("provenance"), str) or not inventory["provenance"].strip():
        raise ValueError("inventory requires operator provenance")
    pending = _task_ids(inventory.get("pending_task_ids"))
    strategy = plan.get("strategy")
    if strategy == "drain":
        if pending or plan.get("pinned_runtime") is not None:
            raise ValueError("drain requires zero pending tasks and no replacement pin")
    elif strategy == "pin":
        pin = plan.get("pinned_runtime")
        if (
            not isinstance(pin, dict)
            or not isinstance(pin.get("image_digest"), str)
            or not IMAGE.fullmatch(pin["image_digest"])
        ):
            raise ValueError("pin requires an immutable Runtime image digest")
        if not pending or _task_ids(pin.get("task_ids")) != pending:
            raise ValueError("pin must cover the exact pending task set")
    else:
        raise ValueError("choose drain or pin explicitly")
    rollback = _artifact(path.parent, plan.get("rollback"))
    if rollback.get("deployment_namespace") != namespace:
        raise ValueError("rollback namespace mismatch")
    image = rollback.get("image_digest")
    if not isinstance(image, str) or not IMAGE.fullmatch(image):
        raise ValueError("rollback requires immutable Runtime image")
    if (
        not isinstance(rollback.get("restore_procedure"), str)
        or not rollback["restore_procedure"].strip()
    ):
        raise ValueError("rollback requires a restore procedure")
    return {
        "schema_version": 1,
        "status": "MATERIALS_CONSISTENT",
        "strategy": strategy,
        "pending_tasks": len(pending),
        "historical_decoder": "retain",
        "live_retirement_authorized": False,
        "provenance_verified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    args = parser.parse_args()
    try:
        result = validate(args.plan)
    except (OSError, ValueError, RecursionError):
        print("Compatibility retirement: BLOCKED (missing, stale or inconsistent evidence)")
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
