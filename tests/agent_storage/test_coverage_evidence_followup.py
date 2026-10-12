"""Bounded P1 owner preflight, callback provenance and original proof regressions."""
# ruff: noqa: F401,F811 - imported pytest fixtures

import pytest

from tests.agent_storage.test_coverage_evidence_operation import (
    acceptance,
    checkpoint,
    dsn,
    evidence,
    metadata,
    model_cloud,
    operation,
    postgres_dsn,
    snapshot,
)


def test_constructor_reads_full_page_once_then_revalidates_at_exit(evidence, monkeypatch):
    from agent_storage.postgres import coverage_evidence_reads as reads

    pages = []
    locked = reads.locked_page

    def page(*args, **kwargs):
        pages.append(True)
        return locked(*args, **kwargs)

    monkeypatch.setattr(reads, "locked_page", page)
    checkpoint(evidence)
    assert len(pages) == 2, "constructor duplicated the fresh full locked page"


def test_unknown_qualifier_is_never_invoked(evidence, monkeypatch):
    env = evidence
    invoked = []

    def unknown(self, derive):
        invoked.append(True)
        raise AssertionError("unknown qualification callback executed")

    owner = operation(env)
    owner._qualify(env.binding)
    monkeypatch.setattr(type(env.cloud), "_execution_receipt_verifier", unknown)
    with pytest.raises(ValueError, match="altered|qualification"):
        owner._qualify(env.binding)
    assert not invoked and metadata(env) is None


def test_acceptance_routing_preflight_precedes_staging_and_upload(evidence, monkeypatch):
    from agent_storage.postgres import coverage_evidence_operation as module

    env = evidence
    checkpoint(env)
    request, writes = acceptance(env)
    before, objects = snapshot(env), len(env.client.objects)

    def unavailable(*args, **kwargs):
        assert all(metadata(env, ident) is None for ident, _ in writes)
        assert len(env.client.objects) == objects
        raise ValueError("routing unavailable before any I/O")

    monkeypatch.setattr(module, "acceptance_evidence_ids", unavailable)
    monkeypatch.setattr(module, "_READ_SELECTOR", unavailable)
    with pytest.raises(ValueError, match="routing unavailable"):
        operation(env).commit_evidence(env.binding, request, writes, fence=env.fence)
    assert snapshot(env) == before and len(env.client.objects) == objects
    assert all(metadata(env, ident) is None for ident, _ in writes)


def test_owned_checkpoint_kernel_consumes_proof_without_duplicate_sql(evidence, monkeypatch):
    from agent_storage.postgres import coverage_model_budget as budget

    sources = []
    original = budget.checkpoint_source

    def source(*args, **kwargs):
        sources.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(budget, "checkpoint_source", source)
    sequence, body = checkpoint(evidence)
    assert sequence > 0 and body == evidence.payload.payload
    assert not sources, "owned reader originals are revalidated at operation exit"


def test_unknown_split_guards_refuse_without_invoking_them(evidence):
    from agent_storage.postgres.coverage_evidence_operation import PostgresCoverageEvidenceOperation

    env = evidence
    invoked = []

    def unknown():
        invoked.append(True)

    env.cloud.check_local_authority = unknown
    env.cloud.check_external_authority = unknown
    owner = PostgresCoverageEvidenceOperation(
        env.store, env.cloud.publisher, env.cloud.authority, env.cloud.check_authority,
        check_local_authority=unknown,
    )
    with pytest.raises(ValueError, match="separated Worker"):
        checkpoint(env, owner)
    assert not invoked and metadata(env) is None


def test_missing_native_prerequisites_are_pre_io_eligibility_only(evidence):
    from agent_storage.postgres.coverage_evidence_selection import CoverageEvidenceUnavailable

    env = evidence
    with env.database.connect() as connection:
        connection.execute("DELETE FROM zebra_schema_migrations WHERE version=93")
    before, objects = snapshot(env), len(env.client.objects)
    with pytest.raises(CoverageEvidenceUnavailable, match="prerequisites"):
        checkpoint(env)
    assert metadata(env) is None and snapshot(env) == before
    assert len(env.client.objects) == objects


def test_postcommit_authority_refusal_keeps_exact_private_receipt_for_replay(evidence):
    from agent_storage.postgres.work_unit import borrow_work_unit

    from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE

    env = evidence
    original = env.cloud.check_authority
    refused = []

    def check():
        original()
        if borrow_work_unit((env.dsn, NAMESPACE)) is None and snapshot(env)[1] == [(1, 30, 0)]:
            refused.append(True)
            raise ValueError("Host revoked after commit")

    env.cloud.check_authority = check
    with pytest.raises(ValueError, match="Host revoked after commit"):
        checkpoint(env)
    assert refused == [True] and metadata(env).lifecycle_status == "finalized"
    before = snapshot(env)
    env.cloud.check_authority = original
    sequence, body = checkpoint(env)
    assert sequence > 0 and body == env.payload.payload and snapshot(env) == before
    assert len(env.requests) == 1


@pytest.mark.parametrize("missing_after_upload", [False, True])
def test_selected_ids_are_frozen_and_post_io_failures_never_offer_fallback(
    evidence, monkeypatch, missing_after_upload,
):
    from uuid import uuid4

    from agent_storage.postgres import coverage_evidence_operation as module
    from agent_storage.postgres.coverage_evidence_selection import CoverageEvidenceUnavailable

    env = evidence
    checkpoint(env)
    request, writes = acceptance(env)
    original, calls = module.acceptance_evidence_ids, []

    def select(*args, **kwargs):
        calls.append(True)
        assert len(calls) == 1, "routing reselected after staging/upload"
        selected = original(*args, **kwargs)
        return (*selected, uuid4()) if missing_after_upload else selected

    monkeypatch.setattr(module, "acceptance_evidence_ids", select)
    monkeypatch.setattr(module, "_READ_SELECTOR", select)
    before = snapshot(env)
    owner = operation(env)
    if missing_after_upload:
        with pytest.raises(ValueError) as refused:
            owner.commit_evidence(env.binding, request, writes, fence=env.fence)
        assert not isinstance(refused.value, CoverageEvidenceUnavailable)
        assert snapshot(env) == before
        assert all(metadata(env, ident).lifecycle_revision == 0 for ident, _ in writes)
    else:
        receipt = owner.commit_evidence(env.binding, request, writes, fence=env.fence)
        assert receipt.event_watermark > 0
    assert calls == [True]


@pytest.mark.parametrize("settled", [False, True])
def test_generic_exit_event_tampering_refuses_and_rolls_back_before_replay(
    evidence, monkeypatch, settled,
):
    from contextlib import contextmanager

    import psycopg
    from agent_storage.postgres.work_unit import borrow_work_unit

    from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE

    env = evidence
    if settled:
        checkpoint(env)
    else:
        env.cloud.store_payload_immutable(env.payload, artifact_id=env.checkpoint.artifact_id)
    before, record = snapshot(env), metadata(env)
    original, attempts = env.cloud._locked_proof_scope, []

    @contextmanager
    def tamper(connection, *args, **kwargs):
        with original(connection, *args, **kwargs) as reader:
            yield reader
            attempts.append(True)
            connection.execute(
                "UPDATE session_events SET created_at=created_at+interval '1 second' "
                "WHERE deployment_namespace=%s AND event_id=%s",
                (NAMESPACE, record.event_binding.event_id),
            )

    with monkeypatch.context() as patch:
        patch.setattr(env.cloud, "_locked_proof_scope", tamper)
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="immutable"):
            env.store.settle_model_checkpoint(env.binding, env.receipt, fence=env.fence)
    assert attempts and snapshot(env) == before and metadata(env) == record
    assert borrow_work_unit((env.dsn, NAMESPACE)) is None
    sequence, body = env.store.settle_model_checkpoint(env.binding, env.receipt, fence=env.fence)
    assert sequence > 0 and body == env.payload.payload and len(env.requests) == 1
