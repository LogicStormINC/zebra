"""Normal work slices versus forced one-unit replacement; controlled transports."""
# ruff: noqa: F811

import json
import os
from collections import defaultdict
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import replace
from functools import partial
from time import perf_counter

import psycopg
import pytest
from agent_core.application.coverage_executor import CoverageExecutor
from agent_core.domain.events import EventType
from agent_core.domain.sessions import SessionStatus
from agent_integrations.coverage_model_invocation import CoverageModelInvocation
from agent_integrations.coverage_snapshot_source import HostCoverageSnapshotSource
from agent_storage import S3ArtifactObjectStore
from agent_storage.postgres.command_wakeup_handoff import HandoffStatus
from agent_storage.postgres.coverage import PostgresCoverageStore
from agent_storage.postgres.coverage_artifact_publication import PostgresCoverageArtifactPublisher
from agent_storage.postgres.coverage_authority import PostgresCoverageAuthority
from agent_storage.postgres.coverage_evidence_operation import PostgresCoverageEvidenceOperation
from agent_storage.postgres.coverage_recovery_preparation import RecoveryReadSnapshot
from agent_storage.postgres.task_admission import load_session_task_binding
from zebra_agent_config.coverage_settings import CoverageWorkSettings
from zebra_agent_worker.coverage_artifacts import CloudCoverageArtifacts
from zebra_agent_worker.coverage_continuation import NATIVE_CONTINUATION_VERIFIER
from zebra_agent_worker.coverage_native_executor import NativeCoverageExecutor
from zebra_agent_worker.coverage_native_model import NativeCoverageModelInvocation
from zebra_agent_worker.coverage_recovery_preparation import NativeCoverageRecoveryCheck

from tests.worker.coverage_model_cloud_fixtures import NAMESPACE, dsn, postgres_dsn  # noqa: F401
from tests.worker.coverage_server_sql_metrics import difference, snapshot
from tests.worker.coverage_work_phase_metrics import observe_phases
from tests.worker.test_coverage_dispatch import (  # noqa: F401
    _stop_native_capability,
    native_handoff,
    native_worker,
)
from tests.worker.test_coverage_multipart import model_cloud, semantic_calls  # noqa: F401


@pytest.fixture
def part_count():
    return 9


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize(
    "model_cloud", [600, {"validation_mode": "final_certification"}],
    indirect=True, ids=["eager", "incremental"],
)
@pytest.mark.parametrize("milliseconds", [2000, 60000])
@pytest.mark.parametrize("execution_receipts", [False, True], ids=["legacy", "atomic"])
@pytest.mark.parametrize("binding_reads", ["fixture", "native"])
@pytest.mark.parametrize("verified_load", [False, True], ids=["legacy-load", "verified-load"])
@pytest.mark.parametrize("batch_routing", [False, True], ids=["full-batches", "scoped-batches"])
@pytest.mark.parametrize("receipt_budget", [False, True], ids=["full-budget", "receipt-budget"])
@pytest.mark.parametrize(
    "load_metadata", [False, True], ids=["legacy-metadata", "verified-metadata"],
)
def test_native_normal_work_slices(
    native_worker, milliseconds, execution_receipts, binding_reads, verified_load, batch_routing,
    receipt_budget, load_metadata, monkeypatch, record_property,
):
    env = native_worker
    env.reply_from_request = True
    if not load_metadata:
        from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
        from agent_core.domain.coverage_model_checkpoint import MAX_MODEL_CHECKPOINT_BYTES
        def legacy_load(self, identifier, kind, *, expected=None):
            # Exact prior metadata flow; frozen-body comparison remains in boundary.
            loaded = self.artifacts.load(
                identifier, kind, MAX_MODEL_CHECKPOINT_BYTES, self._time(),
                mime_type="application/octet-stream" if kind == "coverage_manifest"
                else "application/json",
            )
            if loaded is None:
                return None
            metadata = self.artifacts.store.get_payload(identifier)
            if metadata is None:
                raise CoverageRefusedError(CoverageRefusalReason.ARTIFACT_UNAVAILABLE)
            if metadata.retained_until is not None:
                self._retained_until = min(
                    self._retained_until or metadata.retained_until, metadata.retained_until,
                )
            self._time()
            return loaded[1]

        monkeypatch.setattr(CoverageModelInvocation, "_load", legacy_load)
    import agent_storage.postgres.coverage_model_budget as model_budget

    if not receipt_budget:
        monkeypatch.setattr(model_budget.CoverageModelBudgetQueries, "_receipt_model_policy",
                            lambda *args: None)
    model_initialization_replays = 0
    initialize_replay = model_budget.replay_model

    def full_initialization(*args, **kwargs):
        nonlocal model_initialization_replays
        model_initialization_replays += 1
        return initialize_replay(*args, **kwargs)

    monkeypatch.setattr(model_budget, "replay_model", full_initialization)
    import agent_storage.postgres.coverage_membership as membership

    membership_reads, membership_hits = 0, 0
    read_membership = membership.membership_state

    def counted_membership(*args):
        nonlocal membership_reads, membership_hits
        membership_reads += 1
        root = read_membership(*args)
        membership_hits += root is not None
        return root

    monkeypatch.setattr(membership, "membership_state", counted_membership)
    if not batch_routing:
        from agent_storage.postgres.coverage_model_verification import _ModelVerification

        initialize_verification = _ModelVerification.__init__

        def full_batches(self, *args, **kwargs):
            initialize_verification(self, *args, **kwargs)
            self._batch_record_ids = None

        monkeypatch.setattr(_ModelVerification, "__init__", full_batches)
    if not verified_load:
        import agent_integrations.coverage_snapshot_artifacts as artifact_loading

        # Controlled old-path comparison: disable only this optional capability
        # in the shared loader, not the native reader's physical/authority guards.
        monkeypatch.setattr(artifact_loading, "VerifiedArtifactPayloadReaderPort", ())
    import zebra_agent_worker.coverage_dispatch as dispatch
    import zebra_agent_worker.coverage_recovery as recovery
    import zebra_agent_worker.coverage_recovery_authority as recovery_authority

    binding_read_calls, full_binding_validation_calls = 0, 0
    binding_validation_entries = defaultdict(int)

    def full_binding(*args, entry, **kwargs):
        nonlocal full_binding_validation_calls
        full_binding_validation_calls += 1
        binding_validation_entries[entry] += 1
        return load_session_task_binding(*args, **kwargs)

    # Count direct context preparation too, not just the service's loader alias.
    monkeypatch.setattr(dispatch, "load_session_task_binding",
                        partial(full_binding, entry="dispatch"))
    monkeypatch.setattr(recovery_authority, "load_session_task_binding",
                        partial(full_binding, entry="recovery"))
    if binding_reads == "native":
        def fresh_binding(session):
            nonlocal binding_read_calls
            binding_read_calls += 1
            return full_binding(
                env.dsn, deployment_namespace=NAMESPACE, session_id=session,
                entry="service",
            )

        env.service._task_binding_loader = fresh_binding
    env.service._settings = replace(
        env.service._settings,
        coverage_work=CoverageWorkSettings(max_milliseconds=milliseconds),
    )
    if execution_receipts:
        initialize = PostgresCoverageStore.__init__

        def composed(store, *args, **kwargs):
            initialize(store, *args, **(kwargs | {
                "execution_receipts": True,
                "execution_receipt_verifier": NATIVE_CONTINUATION_VERIFIER,
            }))

        monkeypatch.setattr(PostgresCoverageStore, "__init__", composed)
    before_gets = sum(method == "get_object" for method, _ in env.client.calls)
    before_sends = dict(env.native_object_sends)
    before_puts = sum(method == "put_object" for method, _ in env.client.calls)
    original_execute = psycopg.Connection.execute
    original_cursor_execute = psycopg.Cursor.execute
    original_many = psycopg.Cursor.executemany
    inside_execute = ContextVar("coverage_sql_execute", default=False)
    current_phase = ContextVar("coverage_sql_phase", default="worker_handoff_authority_other")
    queries = 0
    sql_cost = defaultdict(lambda: {"calls": 0, "seconds": 0.0})
    sql_fingerprints = defaultdict(lambda: {"calls": 0, "seconds": 0.0})
    phase_cost = defaultdict(lambda: {"calls": 0, "seconds": 0.0})
    phase_sql_calls = defaultdict(int)
    verifier = recovery._ModelVerification
    full_recovery_transcripts = 0

    def counted_verifier(*args, **kwargs):
        nonlocal full_recovery_transcripts
        full_recovery_transcripts += 1
        return verifier(*args, **kwargs)

    monkeypatch.setattr(recovery, "_ModelVerification", counted_verifier)

    phase_targets = (
        (PostgresCoverageStore, "commit"),
        (NativeCoverageRecoveryCheck, "prepare"),
        (NativeCoverageRecoveryCheck, "prepare_continuation"),
        (PostgresCoverageStore, "_verify_publication_lifecycle"),
        (RecoveryReadSnapshot, "revalidate"),
        (CloudCoverageArtifacts, "_record"),
        (PostgresCoverageArtifactPublisher, "publish"),
        (PostgresCoverageArtifactPublisher, "publish_batch"),
        (PostgresCoverageEvidenceOperation, "publish_model_checkpoint"),
        (PostgresCoverageEvidenceOperation, "commit_evidence"),
        (CoverageExecutor, "execute_batch"),
        (CoverageModelInvocation, "__call__"),
        (NativeCoverageModelInvocation, "_qualified_preparation"),
        (NativeCoverageModelInvocation, "_preparation_boundary"),
        (NativeCoverageModelInvocation, "_mutation_fence"),
    )

    def measured_sql(query, invoke):
        nonlocal queries
        queries += 1
        phase_sql_calls[current_phase.get()] += 1
        sql = str(query).lower()
        category = (
            "reset" if "discard all" in sql else
            "timeout_config" if "set_config" in sql else
            "clock" if "clock_timestamp" in sql else "business"
        )
        stamp = perf_counter()
        token = inside_execute.set(True)
        try:
            return invoke()
        finally:
            inside_execute.reset(token)
            sql_fingerprints[" ".join(sql.split())]["calls"] += 1
            sql_fingerprints[" ".join(sql.split())]["seconds"] += perf_counter() - stamp
            sql_cost[category]["calls"] += 1
            sql_cost[category]["seconds"] += perf_counter() - stamp

    def count(connection, *args, **kwargs):
        return measured_sql(args[0], lambda: original_execute(connection, *args, **kwargs))

    def cursor_count(cursor, *args, **kwargs):
        def invoke():
            return original_cursor_execute(cursor, *args, **kwargs)
        return invoke() if inside_execute.get() else measured_sql(args[0], invoke)

    def many_count(cursor, *args, **kwargs):
        def invoke():
            return original_many(cursor, *args, **kwargs)
        return invoke() if inside_execute.get() else measured_sql(args[0], invoke)

    monkeypatch.setattr(psycopg.Connection, "execute", count)
    monkeypatch.setattr(psycopg.Cursor, "execute", cursor_count)
    monkeypatch.setattr(psycopg.Cursor, "executemany", many_count)
    server_before = snapshot(env.database)
    # SQL statistics snapshots are observer work, outside the original boundary.
    queries = 0
    sql_cost.clear()
    sql_fingerprints.clear()
    phase_sql_calls.clear()
    started, callbacks = perf_counter(), 0
    callback_cost = []
    operation_counters = (
        (PostgresCoverageAuthority, "check"),
        (PostgresCoverageAuthority, "observe"),
        (NativeCoverageExecutor, "_qualified_preparation"),
        (PostgresCoverageEvidenceOperation, "publish_model_checkpoint"),
        (PostgresCoverageEvidenceOperation, "commit_evidence"),
        (HostCoverageSnapshotSource, "_get_descriptor"),
        (S3ArtifactObjectStore, "read_version_verified"),
        (S3ArtifactObjectStore, "put_if_absent"),
    )
    with observe_phases(
        phase_targets, current_phase, phase_cost, counts_only=operation_counters,
    ):
        result, callbacks = _run_callbacks(
            env, callbacks, queries=lambda: queries, callback_cost=callback_cost,
        )
    measured_queries = queries
    elapsed = perf_counter() - started
    measured_gets = sum(method == "get_object" for method, _ in env.client.calls) - before_gets
    measured_sends = {name: count - before_sends[name]
                      for name, count in env.native_object_sends.items()}
    measured_sends["PUT"] = (
        sum(method == "put_object" for method, _ in env.client.calls) - before_puts
    )
    measured_gets += measured_sends["GET"]
    measured_sql_cost, measured_phase_cost = deepcopy(dict(sql_cost)), deepcopy(dict(phase_cost))
    measured_fingerprints = deepcopy(dict(sql_fingerprints))
    measured_phase_sql = dict(phase_sql_calls)
    server_cost = difference(server_before, snapshot(env.database))
    assert sum(cost["calls"] for cost in measured_sql_cost.values()) == measured_queries
    assert sum(cost["calls"] for cost in measured_fingerprints.values()) == measured_queries
    assert sum(measured_phase_sql.values()) == measured_queries
    events = env.events.list_for_session(env.session)
    accepted = [e for e in events if e.event_type is EventType.COVERAGE_BATCH_ACCEPTED]
    assert 2 <= len(accepted) <= 18
    assert sum(e.payload["result_count"] for e in accepted) == 18
    assert len({e.payload["request"]["commit_key"] for e in accepted}) == len(accepted)
    assert sum(e.event_type is EventType.COVERAGE_REPORT_CERTIFIED for e in events) == 1
    assert semantic_calls(env) == 9
    with env.database.connect() as connection:
        receipt_counts = connection.execute(
            "SELECT count(*) AS total,count(*) FILTER "
            "(WHERE body->>'verifier_contract'=%s) AS qualified "
            "FROM coverage_execution_receipts WHERE session_id=%s",
            (NATIVE_CONTINUATION_VERIFIER, env.session),
        ).fetchone()
    if execution_receipts and env.admission.validation_mode == "final_certification":
        assert receipt_counts["total"] == receipt_counts["qualified"] == len(accepted)
        assert full_recovery_transcripts == 0
        assert membership_reads == membership_hits == len(accepted)
        assert not any("unnest(%s::jsonb[])" in sql for sql in measured_fingerprints)
        publication = measured_phase_cost["PostgresCoverageStore._verify_publication_lifecycle"]
        assert publication["calls"] > 0
        if callbacks > 1:
            preparation = measured_phase_cost["NativeCoverageRecoveryCheck.prepare_continuation"]
            assert preparation["calls"] > 0
            if receipt_budget:
                assert model_initialization_replays <= 2  # Only unsealed bootstrap work.
        if binding_reads == "native":
            # Structural gate, not a latency SLO: one cold new-owner handoff,
            # one service load and one execution preparation per wake, plus
            # independent exceptional-recovery setup. An unregistered consumer
            # must not prepare a fourth context before being refused.
            assert full_binding_validation_calls <= (
                3 * callbacks + measured_phase_cost["NativeCoverageRecoveryCheck.prepare"]["calls"]
            ), dict(binding_validation_entries)
    else:
        assert receipt_counts["total"] == 0
    measurement = {
        "native_operation_calls": {
            f"{kind.__name__}.{name}": measured_phase_cost.get(
                f"{kind.__name__}.{name}", {},
            ).get("calls", 0) for kind, name in operation_counters
        },
        "records": 9, "input_bytes": 117, "accepted_units": 18,
        "validation_mode": env.admission.validation_mode,
        "execution_receipts": execution_receipts,
        "full_recovery_transcripts": full_recovery_transcripts,
        "receipt_counts": receipt_counts,
        "callback_cost": callback_cost,
        "work_milliseconds": milliseconds, "callbacks": callbacks,
        "certified_completion_seconds": elapsed, "database_queries": measured_queries,
        "binding_reads": binding_reads, "binding_read_calls": binding_read_calls,
        "full_binding_validation_calls": full_binding_validation_calls,
        "binding_validation_entries": dict(binding_validation_entries),
        "binding_counter_boundary": "service loader versus all coverage context preparations",
        "verified_load": verified_load,
        "batch_routing": batch_routing,
        "receipt_budget": receipt_budget,
        "load_metadata": load_metadata,
        "model_initialization_replays": model_initialization_replays,
        "native_preparation_checks": measured_phase_cost.get(
            "NativeCoverageModelInvocation._qualified_preparation", {},
        ),
        "membership_reads": membership_reads, "membership_hits": membership_hits,
        "object_gets": measured_gets,
        "object_transport_sends": measured_sends,
        "object_transport_boundary": "fixture botocore read _send and fake-client put_object; "
        "counts attempts including failures, not live S3",
        "sql_execute_cost": measured_sql_cost, "inclusive_phase_cost": measured_phase_cost,
        "exclusive_phase_sql_calls": measured_phase_sql,
        "server_sql": server_cost, "accepted_batches": len(accepted),
        "sql_budget": 1000, "sql_budget_met": measured_queries <= 1000,
        "sql_fingerprints": sorted(
            ({"sql": sql, **cost} for sql, cost in measured_fingerprints.items()),
            key=lambda value: value["calls"], reverse=True,
        )[:30],
        "boundary": "after_fixture_setup_before_first_handoff_to_certified_completion",
        "sql_counter_boundary": "Connection/Cursor execute and executemany; no double count; "
        "implicit TX counted only by server monitor; executemany is one client call",
        "handoff_includes_fixture_consumer_lifecycle": True,
        "recovery_counter_excludes_commit_and_publication": True,
        "phase_times_are_nested_not_additive": True,
        "phase_observer": "sys.setprofile code frames; source delegates not replaced",
        "live_e2e": False, "business_accuracy_claim": False,
    }
    record_property("coverage_work_measurement", json.dumps(measurement))
    print(json.dumps(measurement))
    # Diagnostic/baseline runs retain measurements; the release gate cannot
    # confuse structural correctness with the accepted total SQL budget.
    if os.environ.get("ZEBRA_COVERAGE_ENFORCE_SQL_BUDGET") == "1":
        assert measurement["sql_budget_met"], (
            f"certified completion exceeded SQL budget: {measured_queries} > 1000"
        )


def _run_callbacks(env, callbacks, *, queries, callback_cost):
    for _ in range(18):
        callback_start, sql_start = perf_counter(), queries()
        gets_start = (sum(method == "get_object" for method, _ in env.client.calls)
                      + env.native_object_sends["GET"])
        _stop_native_capability(env, remove_revoked=True)
        handoff = native_handoff(env)
        handoff_elapsed = perf_counter() - callback_start
        assert handoff.status is HandoffStatus.ACCEPTED
        result = env.service.execute_claimed_session(handoff.lease, lease_ttl_seconds=300)
        callbacks += 1
        callback_cost.append({
            "handoff_seconds": handoff_elapsed,
            "total_seconds": perf_counter() - callback_start,
            "sql_executes": queries() - sql_start,
            "object_gets": (sum(method == "get_object" for method, _ in env.client.calls)
                            + env.native_object_sends["GET"] - gets_start),
        })
        if result.session.status is SessionStatus.COMPLETED:
            return result, callbacks
        assert result.session.status is SessionStatus.RUNNING
    pytest.fail("normal work slices did not converge")
