"""Draft generic control semantics; no network/model or business adapter."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from agent_storage.postgres.force_stops import PostgresForceStops
from psycopg import OperationalError
from zebra_agent_api.task_force_stop import force_stop_task


def test_acceptance_never_claims_executor_or_resource_release():
    result = PostgresForceStops.public({"task_id": "task", "operation_id": "stop"})
    assert result["request_accepted"] is True
    assert result["state"] == "requested"
    assert result["resources_released"] is False
    assert result["execution"] == result["lease"] == "unconfirmed"
    assert "cancelled" not in result


@pytest.mark.parametrize(
    "execution,lease,sandbox",
    [
        ("unconfirmed", "revoked", "cleaned"),
        ("stopped", "unconfirmed", "cleaned"),
        ("stopped", "revoked", "pending"),
    ],
)
def test_done_without_all_confirmations_requires_reconciliation(execution, lease, sandbox):
    result = PostgresForceStops.public(
        {
            "task_id": "task",
            "operation_id": "stop",
            "phase": "done",
            "execution": execution,
            "lease": lease,
            "sandbox": sandbox,
        }
    )
    assert result["state"] == "requires_reconciliation"
    assert result["resources_released"] is False


def test_only_confirmed_cleanup_releases_and_does_not_expose_authority():
    data = {
        "task_id": "task",
        "operation_id": "stop",
        "phase": "done",
        "execution": "stopped",
        "lease": "revoked",
        "sandbox": "not_required",
        "synchronization": "synchronized",
        "context": "private",
        "executor_acks": {"private": "fence"},
    }
    result = PostgresForceStops.public(data)
    contract = json.loads(
        (
            Path(__file__).resolve().parents[2] / "docs/contracts/cloud-force-stop-v1/contract.json"
        ).read_text()
    )
    assert set(result) == set(contract["response"]["fields"])
    assert result["state"] == "stopped" and result["resources_released"]
    assert not (set(result) & set(contract["response"]["privateFieldsExcluded"]))


@pytest.mark.parametrize("key", [None, "", "   ", "a" * 241, "bad\nkey", "非ASCII"])
def test_invalid_key_is_rejected_before_any_database_or_business_access(key):
    context = object()
    verified = SimpleNamespace(context=context)
    result = force_stop_task(object(), "task", context, key, verified=verified)
    assert result.status_code == 400


def test_unverified_context_cannot_reach_the_force_stop_store():
    result = force_stop_task(object(), "task", object(), "key")
    assert result.status_code == 403


@pytest.mark.parametrize("error_type", [RuntimeError, OperationalError])
def test_control_failure_is_unknown_not_a_false_negative_receipt(monkeypatch, error_type):
    from uuid import uuid4

    import zebra_agent_api.task_force_stop as api

    def fail(*args, **kwargs):
        raise error_type("private backend detail")

    monkeypatch.setattr(
        api, "PostgresForceStops", lambda *args, **kwargs: SimpleNamespace(request=fail)
    )
    control = SimpleNamespace(
        _database=SimpleNamespace(_dsn="unused"), deployment_namespace="native"
    )
    context = object()
    verified = SimpleNamespace(context=context, authority_issuer="https://issuer.example")
    response = api.force_stop_task(
        SimpleNamespace(cloud_control=control),
        str(uuid4()),
        context,
        "stop",
        verified=verified,
        payload={"force": True},
    )
    assert response.status_code == 503
    assert response.body["request_accepted"] is None
    assert response.body["resources_released"] is False
    assert "private backend detail" not in str(response.body)
