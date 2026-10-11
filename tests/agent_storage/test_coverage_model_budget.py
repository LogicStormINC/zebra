"""Real scratch PG only, fixture-owned schemas dropped in the imported fixture's finally."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace

import psycopg
import pytest
from agent_core.application.coverage_semantic import semantic_check
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_core.domain.coverage_model_budget import (
    CoverageModelReservation,
)
from agent_core.domain.coverage_persistence import CoverageRunBinding, coverage_manifest_bytes
from agent_core.domain.coverage_validation import expected_units, manifest_digest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.leases import LeaseLostError
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_integrations.coverage_model_derivation import derive_semantic_observation
from agent_storage import (
    PostgresEventStore,
    PostgresLeaseStore,
    SQLiteArtifactPayloadStore,
    bootstrap_control_plane_epoch,
)
from agent_storage.postgres.coverage import PostgresCoverageStore
from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction

from tests.agent_core.test_coverage_contracts import records, snapshot
from tests.agent_storage.coverage_model_proof_fixtures import (  # noqa: F401
    accounting_certification,
    proof_env,
    source_counts,
)
from tests.agent_storage.test_coverage_publication import _certify, _prepare_publication, _read
from tests.agent_storage.test_postgres_command_wakeup import (  # noqa: F401
    NAMESPACE,
    dsn,
    postgres_dsn,
)
from tests.worker.test_coverage_bootstrap import inputs


@pytest.fixture
def model_env(dsn, tmp_path):  # noqa: F811
    def build(*, calls=2, tokens=100, runtime=60, age=0, source_ref="verified"):
        data = inputs()
        admission = data.admission.model_copy(
            update={
                "contract": data.admission.contract.model_copy(
                    update={"checks": (semantic_check("review").contract_check,)}
                ),
                "max_model_calls": calls,
                "max_model_tokens": tokens,
                "max_runtime_seconds": runtime,
            }
        )
        bootstrap = SessionBootstrapService().build(
            SessionBootstrapCommand(
                title="model ledger fixture",
                user_input="strict",
                workspace_root="/tmp/model-ledger",
                host_context=data.host,
                coverage_admission=admission,
                created_at=datetime.now(UTC) - timedelta(seconds=age),
            )
        )
        # Bind exactly the new Task while preserving the configured Host context.
        from tests.agent_storage.test_command_wakeup import _binding

        binding_data = _binding(
            str(bootstrap.session.session_id),
            tenant=data.host.namespace_id,
            workspace=data.host.workspace_ref,
        ).model_dump()
        binding_data["host_capability"].update(
            host_context=data.host,
            grant_digest=data.task_binding.host_capability.grant_digest,
            grant_expires_at=data.host.expires_at,
        )
        from agent_core.domain.task_bindings import TaskBindingSnapshot

        host_binding = TaskBindingSnapshot.model_validate(binding_data)
        PostgresTaskAdmissionTransaction(dsn, deployment_namespace=NAMESPACE).admit(
            TaskAdmissionRequest(
                events=bootstrap.events,
                session=bootstrap.session,
                workspace=rebuild_workspace(list(bootstrap.events)),
                binding=host_binding,
            )
        )
        with psycopg.connect(dsn) as connection:
            initialized = connection.execute(
                "SELECT 1 FROM control_plane_epochs WHERE deployment_namespace=%s", (NAMESPACE,)
            ).fetchone()
        if initialized is None:
            bootstrap_control_plane_epoch(dsn, deployment_namespace=NAMESPACE)
        leases = PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE)
        lease = leases.acquire(
            bootstrap.session.session_id, owner_instance_id="model-worker", ttl=timedelta(minutes=5)
        )
        artifacts = SQLiteArtifactPayloadStore(tmp_path / f"{bootstrap.session.session_id}.db")
        items = records()
        body = coverage_manifest_bytes(items)
        artifact = artifacts.store_payload(
            ArtifactPayloadWrite(
                session_id=bootstrap.session.session_id,
                kind="coverage-manifest",
                mime_type="application/json",
                payload=body,
                created_at=datetime.now(UTC),
            )
        )
        frozen = snapshot(items).model_copy(
            update={
                "namespace": data.host.namespace_id,
                "source_resource_ref": (
                    data.host.resource_refs[0].resource_id
                    if source_ref == "verified"
                    else source_ref
                ),
                "contract_digest": admission.contract.digest,
                "scope_digest": admission.contract.scope.digest,
                "manifest_digest": manifest_digest(admission.contract, items),
                "manifest_artifact_ref": artifact.uri,
                "as_of": datetime.now(UTC),
                "expires_at": datetime.now(UTC) + timedelta(hours=1),
            }
        )
        binding = CoverageRunBinding(
            namespace=data.host.namespace_id,
            session_id=bootstrap.session.session_id,
            task_id=host_binding.task_id,
            run_id=str(bootstrap.session.session_id),
            contract=admission.contract,
            snapshot=frozen,
            manifest_artifact_digest=sha256(body).hexdigest(),
        )
        store = PostgresCoverageStore(
            dsn,
            deployment_namespace=NAMESPACE,
            artifacts=artifacts,
            supported_model_profiles=("review",),
            model_observation_deriver=derive_semantic_observation,
        )
        store.bind(binding, fence=lease.fence)
        return SimpleNamespace(
            dsn=dsn,
            session=bootstrap.session,
            binding=binding,
            store=store,
            artifacts=artifacts,
            leases=leases,
            fence=lease.fence,
            items=items,
            admission=admission,
        )

    return build


def reserve(env, *, key="call-1", bound=70, unit=None, request="b" * 64):
    policy = env.store.initialize_model_budget(env.binding, fence=env.fence)
    return CoverageModelReservation(
        reservation_key=key,
        admission_digest=policy.admission_digest,
        key=unit or expected_units(env.binding.contract, env.items)[0],
        request_digest=request,
        model_profile="review",
        token_bound=bound,
    )


def spend(env, request):
    return env.store.reserve_model_call(env.binding, request, fence=env.fence)


def usage(env, request, *, total=10):
    from tests.agent_storage.test_coverage_model_checkpoint import publish_checkpoint

    original = publish_checkpoint(env, request)
    return original.model_copy(update={"total_tokens": total})


def charge(env):
    state = env.store.model_budget_state(env.binding)
    return state.calls, state.charged_tokens, state.unresolved


def test_reserve_exact_replay_restart_replacement_and_missing_usage(model_env):
    env = model_env()
    request = reserve(env)
    first = spend(env, request)
    assert first.invoke and charge(env) == (1, 70, 1)
    env.store = PostgresCoverageStore(
        env.dsn,
        deployment_namespace=NAMESPACE,
        artifacts=env.artifacts,
        supported_model_profiles=("review",),
    )
    again = spend(env, request)
    assert not again.invoke and again.event_watermark == first.event_watermark
    original = env.store.model_budget_state(env.binding).policy
    old = env.fence
    env.leases.release(env.session.session_id, fence=old)
    env.fence = env.leases.acquire(
        env.session.session_id, owner_instance_id="replacement", ttl=timedelta(minutes=5)
    ).fence
    with pytest.raises(LeaseLostError):
        env.store.reserve_model_call(env.binding, request, fence=old)
    assert not spend(env, request).invoke
    assert env.store.initialize_model_budget(env.binding, fence=env.fence) == original
    with pytest.raises(CoverageRefusedError):
        spend(env, request.model_copy(update={"reservation_key": "new"}))
    assert charge(env) == (1, 70, 1)


def test_concurrent_workers_cannot_double_spend_tokens(model_env):
    env = model_env()
    request = reserve(env)

    def attempt(index):
        try:
            return spend(
                env, request.model_copy(update={"reservation_key": f"call-{index}"})
            ).invoke
        except CoverageRefusedError:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(attempt, range(4))) == 1
    assert charge(env) == (1, 70, 1)


def test_concurrent_exact_retry_has_only_one_transport_permission(model_env):
    env = model_env()
    request = reserve(env)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(lambda _: spend(env, request).invoke, range(4))) == 1
    assert charge(env) == (1, 70, 1)


def test_valid_receipt_exact_retry_and_rebuild_never_refund_call_count(model_env):
    env = model_env(calls=1)
    request = reserve(env)
    spend(env, request)
    receipt = usage(env, request)
    sequence = env.store.record_model_usage(env.binding, receipt, fence=env.fence)
    assert charge(env) == (1, 10, 0)
    assert env.store.record_model_usage(env.binding, receipt, fence=env.fence) == sequence
    assert not spend(env, request).invoke
    before = source_counts(env)
    with psycopg.connect(env.dsn) as connection:
        connection.execute("DELETE FROM coverage_runs WHERE run_id=%s", (env.binding.run_id,))
    env.store.rebuild(env.binding.namespace, env.binding.run_id)
    assert charge(env) == (1, 10, 0) and source_counts(env) == before
    assert env.store.record_model_usage(env.binding, receipt, fence=env.fence) == sequence
    with pytest.raises(CoverageRefusedError):
        spend(env, request.model_copy(update={"reservation_key": "second", "token_bound": 10}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("input_tokens", True),
        ("output_tokens", 1.0),
        ("total_tokens", None),
        ("total_tokens", 6),
        ("total_tokens", 71),
    ],
)
def test_malformed_usage_remains_fully_charged(model_env, field, value):
    env = model_env()
    request = reserve(env)
    spend(env, request)
    with pytest.raises(ValueError):
        env.store.record_model_usage(
            env.binding, usage(env, request).model_copy(update={field: value}), fence=env.fence
        )
    env.store.rebuild(env.binding.namespace, env.binding.run_id)
    assert charge(env) == (1, 70, 1)


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_digest", "c" * 64),
        ("admission_digest", "d" * 64),
        ("token_bound", 10),
        ("model_profile", "unknown"),
    ],
)
def test_changed_reservation_and_wrong_receipt_refuse_without_refund(model_env, field, value):
    env = model_env()
    request = reserve(env)
    spend(env, request)
    changed = request.model_copy(update={field: value})
    with pytest.raises(ValueError):
        spend(env, changed)
    with pytest.raises(ValueError):
        env.store.record_model_usage(env.binding, usage(env, changed), fence=env.fence)
    assert charge(env) == (1, 70, 1)


def test_wrong_unit_and_unknown_configured_profile_refuse(model_env):
    env = model_env()
    request = reserve(env)
    spend(env, request)
    for key in (
        expected_units(env.binding.contract, env.items)[2],
        request.key.model_copy(update={"part_digest": "f" * 64}),
    ):
        changed = request.model_copy(update={"key": key})
        with pytest.raises(ValueError):
            spend(env, changed)
        with pytest.raises(ValueError):
            env.store.record_model_usage(env.binding, usage(env, changed), fence=env.fence)
    fresh = PostgresCoverageStore(env.dsn, deployment_namespace=NAMESPACE, artifacts=env.artifacts)
    with pytest.raises(ValueError, match="unsupported"):
        fresh.reserve_model_call(
            env.binding,
            request.model_copy(update={"reservation_key": "next", "token_bound": 10}),
            fence=env.fence,
        )
    assert charge(env) == (1, 70, 1)


def test_conflicting_and_unknown_receipt_leave_existing_charge(model_env):
    env = model_env()
    request = reserve(env)
    spend(env, request)
    env.store.record_model_usage(env.binding, usage(env, request), fence=env.fence)
    for receipt in (
        usage(env, request, total=11),
        usage(env, request.model_copy(update={"reservation_key": "unknown"})),
    ):
        with pytest.raises(ValueError):
            env.store.record_model_usage(env.binding, receipt, fence=env.fence)
    assert charge(env) == (1, 10, 0)


@pytest.mark.parametrize(
    "kind", ["coverage_model_call_reserved", "coverage_model_usage_recorded", "task_prepared"]
)
@pytest.mark.parametrize("mutation", ["delete", "tamper"])
def test_pruned_or_tampered_sources_never_reset_budget(model_env, kind, mutation):
    env = model_env()
    request = reserve(env)
    spend(env, request)
    env.store.record_model_usage(env.binding, usage(env, request), fence=env.fence)
    with psycopg.connect(env.dsn) as connection:
        connection.execute("SET LOCAL session_replication_role=replica")
        if mutation == "delete":
            connection.execute(
                "DELETE FROM session_events WHERE session_id=%s AND event_type=%s",
                (env.session.session_id, kind),
            )
        else:
            connection.execute(
                """UPDATE session_events SET payload=payload || '{"tampered":true}'::jsonb
                   WHERE session_id=%s AND event_type=%s""",
                (env.session.session_id, kind),
            )
    for operation in (
        lambda: charge(env),
        lambda: spend(env, request),
        lambda: env.store.rebuild(env.binding.namespace, env.binding.run_id),
    ):
        with pytest.raises(ValueError):
            operation()
    with psycopg.connect(env.dsn) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM coverage_model_calls WHERE run_id=%s", (env.binding.run_id,)
            ).fetchone()[0]
            == 1
        )


def test_missing_initialized_ledger_and_pending_usage_block_strict_certification(model_env):
    env = model_env()
    with pytest.raises(ValueError, match="initialized"):
        accounting_certification(env)
    env.store.initialize_model_budget(env.binding, fence=env.fence)
    accounting_certification(env)
    assert _read(env) is None  # Accounting is not semantic unit proof or issuance.
    pending = model_env()
    spend(pending, reserve(pending))
    with pytest.raises(ValueError, match="unresolved"):
        accounting_certification(pending)


def test_deadline_blocks_new_spend_and_certification_but_keeps_issued_report_readable(
    model_env,
    proof_env,  # noqa: F811
):
    issued = proof_env(runtime=60)
    certificate = _certify(issued)
    unissued = model_env(runtime=2)
    later = reserve(unissued)
    spend(unissued, later)
    _prepare_publication(unissued)
    receipt = usage(unissued, later)
    with psycopg.connect(issued.dsn) as connection:
        connection.execute(
            "SELECT pg_sleep(greatest(2.1,extract(epoch FROM "
            "(%s::timestamptz-clock_timestamp())))+0.03)",
            (issued.store.model_budget_state(issued.binding).policy.deadline,),
        )
    # Original deadline applies even when a callback finishes with valid proof.
    before = source_counts(unissued)
    with pytest.raises(CoverageRefusedError):
        unissued.store.record_model_usage(unissued.binding, receipt, fence=unissued.fence)
    assert charge(unissued) == (1, 70, 1) and source_counts(unissued) == before
    with pytest.raises(CoverageRefusedError):
        spend(unissued, later.model_copy(update={"reservation_key": "next", "token_bound": 10}))
    # Incomplete-set admission now refuses before expensive MODEL proof.
    with pytest.raises(ValueError, match="incomplete|unresolved|deadline"):
        _certify(unissued)
    assert _read(issued)[0] == certificate
    issued.store.rebuild(issued.binding.namespace, issued.binding.run_id)
    assert _read(issued)[0] == certificate
    issued.store.cancel(issued.binding.namespace, issued.binding.run_id, fence=issued.fence)
    with pytest.raises(ValueError):
        _read(issued)


def test_later_task_policy_change_cannot_replace_original_deadline(model_env):
    env = model_env()
    request = reserve(env)
    spend(env, request)
    events = PostgresEventStore(env.dsn, deployment_namespace=NAMESPACE)
    origin = next(
        event
        for event in events.list_for_session(env.session.session_id)
        if event.event_type == EventType.TASK_PREPARED
    )
    payload = dict(origin.payload)
    payload["coverage_admission"] = env.admission.model_copy(
        update={"max_model_calls": 100}
    ).model_dump(mode="json")
    events.append(
        SessionEvent.create(
            session_id=env.session.session_id,
            sequence=events.list_for_session(env.session.session_id)[-1].sequence + 1,
            event_type=EventType.TASK_PREPARED,
            actor=EventActor.HARNESS,
            payload=payload,
        )
    )
    with pytest.raises(ValueError, match="identity changed"):
        spend(env, request)


@pytest.mark.parametrize("variant", ["bool", "float", "extra", "nested_unit", "nested_extra"])
def test_port_reconstructs_nested_typed_forgeries_before_any_mutation(model_env, variant):
    env = model_env()
    request = reserve(env)
    spend(env, request)
    changes = {
        "bool": {"token_bound": True},
        "float": {"token_bound": 70.0},
        "extra": {"unknown": 1},
        "nested_unit": {"key": request.key.model_copy(update={"part_id": False})},
        "nested_extra": {"key": request.key.model_copy(update={"unknown": "hidden"})},
    }
    forged = request.model_copy(update=changes[variant])
    receipt = usage(env, request)
    before = source_counts(env)
    for operation in (
        lambda: spend(env, forged),
        lambda: env.store.record_model_usage(
            env.binding, receipt.model_copy(update={"reservation": forged}), fence=env.fence
        ),
    ):
        with pytest.raises(ValueError):
            operation()
    assert source_counts(env) == before and charge(env) == (1, 70, 1)


@pytest.mark.parametrize("operation", ["reservation", "receipt"])
def test_model_event_index_and_counters_rollback_together(model_env, monkeypatch, operation):
    from agent_storage.postgres import coverage_model_budget

    env = model_env()
    request = reserve(env)
    if operation == "receipt":
        spend(env, request)
    receipt = usage(env, request) if operation == "receipt" else None
    original = coverage_model_budget.witness_event

    def crash(*args):
        original(*args)
        raise RuntimeError("crash after model Event/index")

    before = source_counts(env)
    expected = charge(env)
    with monkeypatch.context() as patch:
        patch.setattr(coverage_model_budget, "witness_event", crash)
        with pytest.raises(RuntimeError):
            if operation == "reservation":
                spend(env, request)
            else:
                env.store.record_model_usage(env.binding, receipt, fence=env.fence)
    assert charge(env) == expected and source_counts(env) == before


def test_reserve_and_receipt_use_native_index_not_full_python_replay(model_env, monkeypatch):
    from agent_storage.postgres import coverage_model_budget

    env = model_env()
    request = reserve(env)

    def forbidden(*args, **kwargs):
        raise AssertionError("mutation hotpath must not allocate/replay full source history")

    monkeypatch.setattr(coverage_model_budget, "replay_model", forbidden)
    spend(env, request)
    env.store.record_model_usage(env.binding, usage(env, request), fence=env.fence)


@pytest.mark.parametrize(
    "table", ["coverage_model_ledger", "coverage_model_events", "coverage_model_calls"]
)
def test_counter_or_proof_conflicts_deny_certification(proof_env, table):  # noqa: F811
    env = proof_env()
    if table == "coverage_model_ledger":
        query = "UPDATE coverage_model_ledger SET charged_tokens=0 WHERE run_id=%s"
    elif table == "coverage_model_events":
        query = "UPDATE coverage_model_events SET event_digest=repeat('0',64) WHERE run_id=%s"
    else:
        query = "UPDATE coverage_model_calls SET receipt=NULL,receipt_sequence=NULL WHERE run_id=%s"
    with psycopg.connect(env.dsn) as connection:
        connection.execute(query, (env.binding.run_id,))
    before = source_counts(env), env.store.counts(env.binding.namespace, env.binding.run_id)
    with pytest.raises(ValueError):
        _certify(env)
    with pytest.raises(ValueError):
        env.store.rebuild(env.binding.namespace, env.binding.run_id)
    assert (
        source_counts(env),
        env.store.counts(env.binding.namespace, env.binding.run_id),
    ) == before


@pytest.mark.parametrize("source_ref", [None, "foreign-history"])
def test_strict_snapshot_without_exact_history_ref_cannot_initialize_reserve_or_certify(
    model_env, source_ref
):
    env = model_env(source_ref=source_ref)
    request = CoverageModelReservation(
        reservation_key="blocked",
        admission_digest="a" * 64,
        key=expected_units(env.binding.contract, env.items)[0],
        request_digest="b" * 64,
        model_profile="review",
        token_bound=10,
    )
    before = source_counts(env)
    for operation in (
        lambda: env.store.initialize_model_budget(env.binding, fence=env.fence),
        lambda: spend(env, request),
    ):
        with pytest.raises(ValueError, match="run/history/Task binding"):
            operation()
    assert source_counts(env) == before
    _prepare_publication(env)
    with pytest.raises(ValueError, match="run/history/Task binding"):
        env.store.commit(env.request, fence=env.fence)
    before = source_counts(env)
    # No accepted results: the independent complete-set gate runs first.
    with pytest.raises(ValueError, match="incomplete|run/history/Task binding"):
        _certify(env)
    assert source_counts(env) == before
    with psycopg.connect(env.dsn) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM coverage_model_ledger WHERE run_id=%s", (env.binding.run_id,)
            ).fetchone()[0]
            == 0
        )
