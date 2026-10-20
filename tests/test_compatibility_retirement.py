"""Offline material consistency cannot authorize a destructive retirement."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.validate_compatibility_retirement import validate

NOW = datetime(2026, 10, 20, tzinfo=UTC)


def _write(path, data):
    path.write_text(json.dumps(data))
    return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def materials(tmp_path, pending=()):
    plan = {
        "schema_version": 1,
        "deployment_namespace": "existing-namespace",
        "compatibility": ["trench_messages", "coverage_v1"],
        "historical_decoder": "retain",
        "strategy": "drain",
        "pinned_runtime": None,
        "inventory": _write(
            tmp_path / "inventory.json",
            {
                "deployment_namespace": "existing-namespace",
                "compatibility": ["trench_messages", "coverage_v1"],
                "observed_at": NOW.isoformat(),
                "pending_task_ids": list(pending),
                "provenance": "synthetic test inventory",
            },
        ),
        "rollback": _write(
            tmp_path / "rollback.json",
            {
                "deployment_namespace": "existing-namespace",
                "image_digest": "sha256:" + "a" * 64,
                "restore_procedure": "Fixture: retain storage and start pinned image",
            },
        ),
    }
    path = tmp_path / "plan.json"
    _write(path, plan)
    return path, plan


def test_explicit_drain_is_only_offline_material_consistency(tmp_path):
    path, _ = materials(tmp_path)
    result = validate(path, now=NOW)
    assert result["status"] == "MATERIALS_CONSISTENT"
    assert result["live_retirement_authorized"] is False
    assert result["provenance_verified"] is False
    assert result["historical_decoder"] == "retain"


def test_example_blocks_without_real_material():
    with pytest.raises(ValueError, match="evidence"):
        validate(Path(__file__).parents[1] / "configs/compatibility_retirement.example.json")


def test_pending_task_requires_exact_immutable_pin(tmp_path):
    path, plan = materials(tmp_path, ["old-task"])
    with pytest.raises(ValueError, match="zero pending"):
        validate(path, now=NOW)
    plan.update(
        strategy="pin",
        pinned_runtime={"image_digest": "sha256:" + "b" * 64, "task_ids": ["old-task"]},
    )
    _write(path, plan)
    assert validate(path, now=NOW)["pending_tasks"] == 1
    plan["pinned_runtime"]["task_ids"] = ["unrelated-task"]
    _write(path, plan)
    with pytest.raises(ValueError, match="exact pending"):
        validate(path, now=NOW)


@pytest.mark.parametrize(
    "change", ["digest", "namespace", "stale", "future", "naive", "duplicate", "missing"]
)
def test_bad_inventory_cannot_retire(tmp_path, change):
    path, plan = materials(tmp_path)
    evidence = tmp_path / "inventory.json"
    data = json.loads(evidence.read_text())
    if change == "namespace":
        data["deployment_namespace"] = "other-product"
    elif change == "stale":
        data["observed_at"] = (NOW - timedelta(days=2)).isoformat()
    elif change == "future":
        data["observed_at"] = (NOW + timedelta(seconds=1)).isoformat()
    elif change == "naive":
        data["observed_at"] = NOW.replace(tzinfo=None).isoformat()
    elif change == "duplicate":
        data["pending_task_ids"] = ["old-task", "old-task"]
    elif change == "missing":
        del data["pending_task_ids"]
    plan["inventory"] = _write(evidence, data)
    if change == "digest":
        evidence.write_text("{}")
    _write(path, plan)
    with pytest.raises(ValueError):
        validate(path, now=NOW)


@pytest.mark.parametrize("change", ["decoder", "unknown", "tag", "rollback", "bool_schema"])
def test_unsupported_retirement_or_rollback_is_refused(tmp_path, change):
    path, plan = materials(tmp_path)
    if change == "decoder":
        plan["historical_decoder"] = "delete"
    elif change == "unknown":
        plan["compatibility"] = ["all"]
    elif change == "bool_schema":
        plan["schema_version"] = True
    else:
        data = json.loads((tmp_path / "rollback.json").read_text())
        data["image_digest" if change == "tag" else "restore_procedure"] = (
            "latest" if change == "tag" else ""
        )
        plan["rollback"] = _write(tmp_path / "rollback.json", data)
    _write(path, plan)
    with pytest.raises(ValueError):
        validate(path, now=NOW)


@pytest.mark.parametrize(
    "selection", [["trench_messages"], ["coverage_v1"], ["schedule_exchange_legacy"]]
)
def test_inventory_cannot_be_reused_for_a_different_compatibility_set(tmp_path, selection):
    path, plan = materials(tmp_path)
    plan["compatibility"] = selection
    _write(path, plan)
    with pytest.raises(ValueError, match="exact compatibility"):
        validate(path, now=NOW)
