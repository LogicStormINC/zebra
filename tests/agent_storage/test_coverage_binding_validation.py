"""Raw typed bindings must refuse before shared-boundary I/O or any PG mutation."""

from unittest.mock import Mock
from uuid import UUID

import psycopg
import pytest
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.coverage_task_admission import coverage_admission_input
from agent_core.domain.leases import LeaseFence
from agent_storage.postgres.coverage_transactions import (
    assert_projection,
    lock_run,
    validate_write,
    validated_binding,
)
from psycopg import sql

from tests.agent_core.test_coverage_contracts import contract, records, snapshot
from tests.agent_storage.test_coverage_model_budget import (
    model_env,  # noqa: F401
    reserve,
    spend,
    usage,
)
from tests.agent_storage.test_postgres_command_wakeup import dsn, postgres_dsn  # noqa: F401

VARIANTS = (
    "binding_extra",
    "binding_pydantic_extra",
    "snapshot_extra",
    "snapshot_pydantic_extra",
    "contract_extra",
    "record_count_float",
    "record_count_bool",
    "revision_float",
)


def forged(binding, variant):
    if variant == "binding_extra":
        return binding.model_copy(update={"unknown": True})
    if variant == "binding_pydantic_extra":
        value = binding.model_copy()
        object.__setattr__(value, "__pydantic_extra__", {"unknown": True})
        return value
    if variant == "contract_extra":
        return binding.model_copy(
            update={"contract": binding.contract.model_copy(update={"unknown": True})}
        )
    if variant == "revision_float":
        return binding.model_copy(
            update={
                "contract": binding.contract.model_copy(
                    update={"contract_revision": float(binding.contract.contract_revision)}
                )
            }
        )
    source = binding.snapshot.model_copy()
    if variant == "snapshot_pydantic_extra":
        object.__setattr__(source, "__pydantic_extra__", {"unknown": True})
    else:
        changes = {
            "snapshot_extra": {"unknown": True},
            "record_count_float": {"record_count": float(source.record_count)},
            "record_count_bool": {"record_count": True},
        }
        source = source.model_copy(update=changes[variant])
    return binding.model_copy(update={"snapshot": source})


def canonical_binding():
    identity = UUID("00000000-0000-0000-0000-000000000001")
    return CoverageRunBinding(
        namespace="tenant-1",
        session_id=identity,
        task_id=identity,
        run_id="binding-check",
        contract=contract(),
        snapshot=snapshot(records()),
        manifest_artifact_digest="a" * 64,
    )


def test_raw_binding_revalidation_preserves_uuid_identifiers_and_canonical_meaning():
    value = canonical_binding()
    assert coverage_admission_input(value)["session_id"] is value.session_id
    rebuilt = validated_binding(value)
    assert rebuilt == value and rebuilt.model_dump(mode="json") == value.model_dump(mode="json")
    assert isinstance(rebuilt.session_id, UUID) and isinstance(rebuilt.task_id, UUID)


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("boundary", ["lock", "write", "projection"])
def test_shared_boundaries_reject_forgeries_before_io(variant, boundary):
    connection = Mock()
    value = forged(canonical_binding(), variant)
    fence = LeaseFence(control_plane_epoch=UUID(int=1), fencing_token=1, owner_instance_id="test")
    with pytest.raises(ValueError):
        if boundary == "lock":
            lock_run(connection, "deployment", value, None)
        elif boundary == "write":
            validate_write(connection, "deployment", value, fence)
        else:
            assert_projection(connection, "deployment", value, Mock())
    assert connection.mock_calls == []


def database_rows(env):
    """Compare full row contents in this fixture's own schema, not only counts."""
    with psycopg.connect(env.dsn) as connection:
        tables = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname=current_schema() ORDER BY tablename"
        ).fetchall()
        return {
            table: connection.execute(
                sql.SQL("SELECT to_jsonb(t) FROM {} t ORDER BY to_jsonb(t)::text").format(
                    sql.Identifier(table)
                )
            ).fetchall()
            for (table,) in tables
        }


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize(
    "operation", ["initialize", "reserve", "usage", "state", "attempt", "bind"]
)
def test_forged_binding_cannot_change_any_real_pg_row(model_env, variant, operation):  # noqa: F811
    env = model_env()
    request = None
    if operation != "initialize":
        request = reserve(env)
    if operation in {"usage", "state"}:
        spend(env, request)
    receipt = usage(env, request) if operation == "usage" else None
    value = forged(env.binding, variant)
    before = database_rows(env)
    with pytest.raises(ValueError):
        if operation == "initialize":
            env.store.initialize_model_budget(value, fence=env.fence)
        elif operation == "reserve":
            env.store.reserve_model_call(value, request, fence=env.fence)
        elif operation == "usage":
            env.store.record_model_usage(value, receipt, fence=env.fence)
        elif operation == "state":
            env.store.model_budget_state(value)
        elif operation == "attempt":
            env.store.reserve_attempt(
                value,
                request.key,
                input_bytes=1,
                budget=env.admission.execution_budget,
                fence=env.fence,
            )
        else:
            env.store.bind(value, fence=env.fence)
    assert database_rows(env) == before
