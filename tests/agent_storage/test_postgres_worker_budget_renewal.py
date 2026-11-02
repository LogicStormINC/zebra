"""Real PG: authority renewal moves only the budget reference, never prior spend."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_core.domain.host_authority import HostResourceRef
from agent_core.domain.task_bindings import host_context_digest
from agent_core.ports.worker_budget import WorkerBudgetError
from agent_storage.postgres import task_admission
from agent_storage.postgres.task_admission import load_task_binding, save_task_binding
from zebra_agent_api.session_binding import renew_task_binding_snapshot

from tests.agent_storage.test_postgres_worker_budget import dsn as shared_dsn
from tests.agent_storage.test_postgres_worker_budget import request, started
from tests.agent_storage.test_postgres_worker_budget import setup as shared_setup

dsn, setup = shared_dsn, shared_setup


def renewal(database, binding):
    old = load_task_binding(
        database._dsn, deployment_namespace=database.deployment_namespace,
        task_id=binding.task_id,
    )
    fresh = old.host_capability.host_context.model_copy(update={
        "grant_id": str(uuid4()), "expires_at": datetime.now(UTC) + timedelta(minutes=10),
    })
    return old, renew_task_binding_snapshot(old, fresh)


def save(database, renewed, previous=1):
    return save_task_binding(
        database._dsn, deployment_namespace=database.deployment_namespace,
        binding=renewed, expected_previous_revision=previous,
    )


def snapshot(database, binding):
    with database.connect() as c:
        row = c.execute(
            "SELECT * FROM worker_task_budgets WHERE deployment_namespace=%s AND task_id=%s",
            (database.deployment_namespace, binding.task_id),
        ).fetchone()
        models = c.execute(
            "SELECT * FROM worker_model_reservations WHERE deployment_namespace=%s "
            "AND task_id=%s ORDER BY reservation_id",
            (database.deployment_namespace, binding.task_id),
        ).fetchall()
    return row, models


def test_valid_renewal_preserves_all_charges_unknown_and_absolute_clock(setup):
    store, binding, database = started(setup)
    known = store.reserve_model(binding, request(30))
    store.settle_model(binding, known, {
        "prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15,
    }, "original-provider-receipt")
    store.reserve_model(binding, request(30))  # Unknown original must remain charged.
    store.reserve_tool(binding, str(uuid4()))
    before, models = snapshot(database, binding)
    old, renewed = renewal(database, binding)
    save(database, renewed)
    after, after_models = snapshot(database, binding)
    assert after == {**before, "binding_digest": renewed.binding_digest}
    assert after_models == models
    assert old.binding_digest != renewed.binding_digest
    with pytest.raises(WorkerBudgetError):
        store.check(binding)
    current = replace(binding, binding_digest=renewed.binding_digest, attempt_number=2)
    store.start(current)
    assert store.check(current) > 0
    with pytest.raises(WorkerBudgetError, match="unknown original"):
        store.reserve_model(current, request(30))
    final, final_models = snapshot(database, binding)
    assert final["started_at"] == before["started_at"]
    assert final["deadline"] == before["deadline"]
    assert final["charged_tokens"] == 45 and final["tool_calls"] == 1
    assert final_models == models


def test_renewal_does_not_revive_expired_task(setup):
    store, binding, database = started(setup)
    with database.connect() as c:
        c.execute(
            "UPDATE worker_task_budgets SET deadline=clock_timestamp()-interval '1 second' "
            "WHERE deployment_namespace=%s AND task_id=%s",
            (database.deployment_namespace, binding.task_id),
        )
    before, _ = snapshot(database, binding)
    _, renewed = renewal(database, binding)
    save(database, renewed)
    after, _ = snapshot(database, binding)
    assert after == {**before, "binding_digest": renewed.binding_digest}
    with pytest.raises(WorkerBudgetError, match="absolute deadline"):
        store.start(replace(binding, binding_digest=renewed.binding_digest))
    assert snapshot(database, binding)[0] == after


@pytest.mark.parametrize("change", [
    "issuer", "principal", "workspace", "thread", "scope", "limits", "frozen_policy",
    "unhashed_connector", "unhashed_profile",
])
def test_changed_authority_cannot_transfer_existing_budget(setup, change):
    _, binding, database = started(setup)
    _, renewed = renewal(database, binding)
    host = renewed.host_capability
    context = host.host_context
    if change == "issuer":
        host = host.model_copy(update={"authority_issuer": "https://other.example"})
    elif change in {"principal", "thread"}:
        context = context.model_copy(update={"resource_refs": tuple(
            HostResourceRef(type=ref.resource_type, id="other")
            if ref.resource_type == change else ref for ref in context.resource_refs
        )})
    elif change == "workspace":
        context = context.model_copy(update={"workspace_ref": "other"})
    elif change == "scope":
        context = context.model_copy(update={"scopes": (*context.scopes, "artifact.publish")})
    elif change == "limits":
        context = context.model_copy(update={"limits": context.limits.model_copy(
            update={"max_model_tokens": 101},
        )})
    elif change == "unhashed_connector":
        host = host.model_copy(update={"connector_id": "other"})
    elif change == "unhashed_profile":
        ceiling = renewed.agent_capability_ceiling.model_copy(
            update={"capability_profile_ref": "other@1"},
        )
        renewed = renewed.model_copy(update={"agent_capability_ceiling": ceiling})
    else:
        renewed = renewed.model_copy(update={"zebra_policy_digest": "f" * 64})
    host = host.model_copy(update={
        "host_context": context, "grant_digest": host_context_digest(context),
    })
    renewed = renewed.model_copy(update={"host_capability": host})
    before = snapshot(database, binding)
    with pytest.raises(ValueError):
        save(database, renewed)
    assert snapshot(database, binding) == before
    assert load_task_binding(database._dsn, deployment_namespace=database.deployment_namespace,
                             task_id=binding.task_id).binding_revision == 1


def test_failed_snapshot_transaction_rolls_back_budget_reference(setup, monkeypatch):
    _, binding, database = started(setup)
    _, renewed = renewal(database, binding)
    original = task_admission._insert_binding_snapshot

    def fail_after_insert(*args):
        original(*args)
        raise RuntimeError("injected transaction failure")

    monkeypatch.setattr(task_admission, "_insert_binding_snapshot", fail_after_insert)
    before = snapshot(database, binding)
    with pytest.raises(RuntimeError, match="injected"):
        save(database, renewed)
    assert snapshot(database, binding) == before
    assert load_task_binding(database._dsn, deployment_namespace=database.deployment_namespace,
                             task_id=binding.task_id).binding_revision == 1


def test_stale_budget_digest_is_not_implicitly_repaired(setup):
    _, binding, database = started(setup)
    _, renewed = renewal(database, binding)
    with database.connect() as c:
        c.execute(
            "UPDATE worker_task_budgets SET binding_digest=%s "
            "WHERE deployment_namespace=%s AND task_id=%s",
            ("0" * 64, database.deployment_namespace, binding.task_id),
        )
    before = snapshot(database, binding)
    with pytest.raises(ValueError):
        save(database, renewed)
    assert snapshot(database, binding) == before
    assert load_task_binding(database._dsn, deployment_namespace=database.deployment_namespace,
                             task_id=binding.task_id).binding_revision == 1


def test_budget_transfer_requires_cas(setup):
    _, binding, database = started(setup)
    _, renewed = renewal(database, binding)
    before = snapshot(database, binding)
    with pytest.raises(ValueError):
        save(database, renewed, previous=None)
    assert snapshot(database, binding) == before


def test_valid_renewal_without_budget_does_not_allocate_one(setup):
    from agent_storage.postgres.database import PostgresDatabase

    uri, ns, authority = setup
    database = PostgresDatabase(uri, deployment_namespace=ns)
    old = load_task_binding(uri, deployment_namespace=ns, task_id=str(authority.parent_task_id))
    fresh = old.host_capability.host_context.model_copy(update={"grant_id": str(uuid4())})
    renewed = renew_task_binding_snapshot(old, fresh)
    save(database, renewed)
    assert load_task_binding(uri, deployment_namespace=ns,
                             task_id=str(authority.parent_task_id)) == renewed
    with database.connect() as c:
        assert c.execute("SELECT count(*) AS n FROM worker_task_budgets "
                         "WHERE deployment_namespace=%s AND task_id=%s",
                         (ns, str(authority.parent_task_id))).fetchone()["n"] == 0


def test_valid_narrowing_keeps_prior_spend_and_only_reduces_limits(setup):
    store, binding, database = started(setup)
    store.reserve_tool(binding, str(uuid4()))
    old, fresh = renewal(database, binding)
    context = fresh.host_capability.host_context
    narrowed = context.model_copy(update={"limits": context.limits.model_copy(
        update={"max_model_tokens": 50, "max_runtime_seconds": 30},
    )})
    renewed = renew_task_binding_snapshot(old, narrowed)
    before, _ = snapshot(database, binding)
    save(database, renewed)
    current = replace(binding, binding_digest=renewed.binding_digest,
                      max_model_tokens=50, max_runtime_seconds=30, attempt_number=2)
    store.start(current)
    after, _ = snapshot(database, binding)
    assert after["started_at"] == before["started_at"]
    assert after["deadline"] == before["started_at"] + timedelta(seconds=30)
    assert after["deadline"] < before["deadline"]
    assert after["max_model_tokens"] == 50 and after["tool_calls"] == 1


def test_corrupt_prior_snapshot_digest_cannot_transfer_budget(setup):
    _, binding, database = started(setup)
    _, renewed = renewal(database, binding)
    with database.connect() as c:
        c.execute(
            "UPDATE task_binding_snapshots SET binding_digest=%s "
            "WHERE deployment_namespace=%s AND task_id=%s AND binding_revision=1",
            ("0" * 64, database.deployment_namespace, binding.task_id),
        )
    before = snapshot(database, binding)
    with pytest.raises(ValueError, match="prior binding"):
        save(database, renewed)
    assert snapshot(database, binding) == before
    with database.connect() as c:
        assert c.execute(
            "SELECT count(*) AS n FROM task_binding_snapshots "
            "WHERE deployment_namespace=%s AND task_id=%s",
            (database.deployment_namespace, binding.task_id),
        ).fetchone()["n"] == 1
