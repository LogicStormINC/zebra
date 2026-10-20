"""Native pure preparation never observes SQL/Host; unknown delegates stay guarded."""
# ruff: noqa: F401,F811

from dataclasses import replace
from types import FunctionType
from unittest.mock import Mock

import httpx
import psycopg
import pytest
from agent_core.domain.coverage_contracts import CoverageRefusedError
from agent_core.domain.coverage_model_checkpoint import MODEL_CHECKPOINT_KIND
from agent_core.domain.sessions import SessionStatus
from agent_integrations.coverage_model import SemanticCoverageModel
from agent_integrations.coverage_model_derivation import derive_semantic_observation
from agent_integrations.coverage_snapshot_source import HostCoverageSnapshotSource
from zebra_agent_config.coverage_settings import CoverageWorkSettings
from zebra_agent_worker.coverage_native_model import (
    NativeCoverageModelInvocation,
    NativeSemanticCoverageModel,
    _closure,
    qualified_final_reads,
)
from zebra_agent_worker.execution_finalization import WorkerExecutionError

from tests.worker.coverage_model_cloud_fixtures import dsn, model_cloud, postgres_dsn
from tests.worker.test_coverage_dispatch import native_handoff, native_worker


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [
    {"validation_mode": "final_certification"},
    {"validation_mode": "final_certification", "v2": True},
], indirect=True)
def test_native_pure_blocks_and_changed_delegate_fallback(native_worker, monkeypatch):
    import zebra_agent_worker.coverage_dispatch as dispatch

    env = native_worker
    env.service._settings = replace(
        env.service._settings, coverage_work=CoverageWorkSettings(max_milliseconds=60000),
    )
    checked = False

    def compose(**kwargs):
        nonlocal checked
        invocation = kwargs["invoke_or_replay"]
        semantic = NativeSemanticCoverageModel(**kwargs)
        assert type(invocation) is NativeCoverageModelInvocation
        assert invocation._qualified_preparation()
        source = invocation.artifacts.store
        native = _closure(source.check_local_authority)["check_local_native"]
        authority = _closure(native)["execution_authority"]

        def unexpected(*args, **kwargs):
            pytest.fail("pure native preparation dispatched SQL or Host I/O")

        with monkeypatch.context() as patch:
            patch.setattr(psycopg.Connection, "execute", unexpected)
            patch.setattr(HostCoverageSnapshotSource, "_get_descriptor", unexpected)
            for _ in range(32):
                invocation._preparation_boundary()
                assert invocation._mutation_fence() == invocation._owned_fence
                semantic._authorize()

        for target, name in (
            (invocation, "gateway_factory"), (invocation, "fresh_fence"),
            (invocation.store, "reserve_model_call"),
            (invocation.artifacts.store, "store_payload_immutable"),
            (invocation.artifacts.store.publisher, "publish_batch"),
            (invocation.artifacts, "load"),
            (invocation.artifacts.store, "check_local_authority"),
            (invocation.artifacts.store, "check_external_authority"),
            (invocation.artifacts.store.metadata, "get_metadata"),
            (invocation.store, "_model_observation_deriver"),
            (authority, "observe"),
        ):
            original = getattr(target, name)
            with monkeypatch.context() as patch:
                patch.setattr(
                    target, name, lambda *args, _original=original, **kwargs:
                    _original(*args, **kwargs),
                )
                assert not invocation._qualified_preparation()
                # Replacing an I/O delegate never inherits SQL-free preparation.
                with patch.context() as guard:
                    guard.setattr(psycopg.Connection, "execute", unexpected)
                    with pytest.raises(pytest.fail.Exception, match="dispatched SQL"):
                        invocation._preparation_boundary()
                    with pytest.raises(pytest.fail.Exception, match="dispatched SQL"):
                        semantic._authorize()
        with monkeypatch.context() as patch:
            patch.setattr(invocation, "now", lambda: invocation.policy.deadline)
            assert not invocation._qualified_preparation()
            with pytest.raises(CoverageRefusedError):
                invocation._preparation_boundary()
        with monkeypatch.context() as patch:
            patch.setattr(semantic, "_invoke_or_replay", lambda *args: invocation(*args))
            patch.setattr(psycopg.Connection, "execute", unexpected)
            with pytest.raises(pytest.fail.Exception, match="dispatched SQL"):
                semantic._authorize()
        classifier = type(invocation)._qualified_preparation

        def forged_classifier():
            pytest.fail("untrusted classifier was executed")

        with monkeypatch.context() as patch:
            patch.setattr(invocation, "_qualified_preparation", forged_classifier)
            assert not classifier(invocation)
            patch.setattr(psycopg.Connection, "execute", unexpected)
            for operation in (
                invocation._preparation_boundary, invocation._mutation_fence, semantic._authorize,
            ):
                with pytest.raises(pytest.fail.Exception, match="dispatched SQL"):
                    operation()
        checked = True
        return semantic

    monkeypatch.setattr(dispatch, "NativeSemanticCoverageModel", compose)
    handoff = native_handoff(env)
    result = env.service.execute_claimed_session(handoff.lease, lease_ttl_seconds=300)
    assert checked and result.session.status is SessionStatus.COMPLETED


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [
    {"validation_mode": "final_certification"},
    {"validation_mode": "final_certification", "v2": True},
], indirect=True)
def test_model_response_revocation_stops_before_checkpoint_publication(native_worker, monkeypatch):
    env = native_worker
    handle = httpx.MockTransport.handle_request
    revoked = False

    def response(transport, request):
        nonlocal revoked
        result = handle(transport, request)
        if request.url.host == "api.deepseek.com" and request.url.path == "/chat/completions":
            with env.database.connect() as connection:
                connection.execute(
                    "UPDATE session_projections SET status='cancelled' "
                    "WHERE deployment_namespace=%s AND session_id=%s",
                    (env.database.deployment_namespace, env.session),
                )
            revoked = True
        return result

    monkeypatch.setattr(httpx.MockTransport, "handle_request", response)
    handoff = native_handoff(env)
    with pytest.raises(WorkerExecutionError, match="strict coverage refused: authority_invalid"):
        env.service.execute_claimed_session(handoff.lease, lease_ttl_seconds=300)
    assert revoked
    with env.database.connect() as connection:
        ledger = connection.execute(
            "SELECT l.calls,l.unresolved,l.charged_tokens FROM coverage_model_ledger l "
            "JOIN coverage_model_summary s USING (deployment_namespace,namespace,run_id) "
            "WHERE l.deployment_namespace=%s AND s.session_id=%s",
            (env.database.deployment_namespace, env.session),
        ).fetchall()
        checkpoint = connection.execute(
            "SELECT 1 FROM artifact_payload_metadata WHERE deployment_namespace=%s "
            "AND session_id=%s AND kind=%s",
            (env.database.deployment_namespace, env.session, MODEL_CHECKPOINT_KIND),
        ).fetchall()
        delivered = connection.execute(
            "SELECT 1 FROM session_events WHERE deployment_namespace=%s AND session_id=%s "
            "AND event_type=ANY(%s)",
            (env.database.deployment_namespace, env.session,
             ["coverage_model_usage_recorded", "coverage_report_certified"]),
        ).fetchall()
    assert len(ledger) == 1 and ledger[0]["calls"] == ledger[0]["unresolved"] == 1
    assert ledger[0]["charged_tokens"] > 0
    assert not checkpoint and not delivered


@pytest.mark.parametrize("native_worker", ["first_create"], indirect=True)
@pytest.mark.parametrize("model_cloud", [
    {"validation_mode": "final_certification"},
    {"validation_mode": "final_certification", "v2": True},
], indirect=True)
def test_native_final_proof_owns_fresh_bytes_and_clears_on_failure(native_worker, monkeypatch):
    import zebra_agent_worker.coverage_dispatch as dispatch

    env, checked = native_worker, False
    env.service._settings = replace(
        env.service._settings, coverage_work=CoverageWorkSettings(max_milliseconds=60000),
    )

    def compose(**kwargs):
        nonlocal checked
        invocation = kwargs["invoke_or_replay"]
        source, identifier = invocation.artifacts.store, invocation.manifest_id
        assert qualified_final_reads(source)
        prior = dict(source._verified_payloads)
        read = Mock(wraps=source.objects.read_version_verified)

        def scope(connection):
            return source._locked_proof_scope(
                connection, source.deployment, source.binding,
                derive=derive_semantic_observation, final_certification=True,
            )

        with monkeypatch.context() as patch:
            patch.setattr(source.objects, "read_version_verified", read)
            for count in (1, 2):
                with source.metadata._database.connect() as connection:
                    with scope(connection) as reader:
                        assert reader.reuse_verified_payloads
                        assert reader._verified_payload_owner is reader
                        assert not reader._verified_payloads
                        first = reader.read_payload_bytes(identifier)
                        assert reader.read_payload_bytes(identifier) == first
                        assert read.call_count == count
                    assert not reader._verified_payloads and reader._verified_bytes == 0
                    with pytest.raises(RuntimeError, match="ended"):
                        reader.read_payload_bytes(identifier)
            # A new certification must physically read, even with populated
            # execution bytes. No previous proof can hide post-append corruption.
            read.side_effect = ValueError("object corrupted")
            with source.metadata._database.connect() as connection:
                with pytest.raises(ValueError, match="corrupted"), scope(connection) as reader:
                    reader.read_payload_bytes(identifier)
                assert not reader._verified_payloads and reader._verified_bytes == 0
            read.side_effect = None
            with source.metadata._database.connect() as connection:
                with pytest.raises(ValueError, match="exit revoked"), scope(connection) as reader:
                    reader.read_payload_bytes(identifier)
                    patch.setattr(source, "check_authority", Mock(
                        side_effect=ValueError("exit revoked"),
                    ))
                assert not reader._verified_payloads and reader._verified_bytes == 0
        assert source._verified_payloads == prior  # Final never inherits or overwrites it.
        # Same Worker bytecode is insufficient: split callbacks must belong to
        # this check closure, not another callable with copied code/globals.
        local = source.check_local_authority
        foreign = FunctionType(local.__code__, local.__globals__, closure=local.__closure__)
        with monkeypatch.context() as patch:
            patch.setattr(source, "check_local_authority", foreign)
            assert not qualified_final_reads(source)
            with source.metadata._database.connect() as connection:
                with scope(connection) as reader:
                    assert not reader.reuse_verified_payloads
        for target, name in (
            (source, "read_payload_verified_bounded"),
            (source.metadata, "get_metadata"), (source.publisher, "publish_batch"),
        ):
            method = getattr(target, name)
            with monkeypatch.context() as patch:
                patch.setattr(target, name, lambda *a, _method=method, **k: _method(*a, **k))
                assert not qualified_final_reads(source)
        checked = True
        return NativeSemanticCoverageModel(**kwargs)

    monkeypatch.setattr(dispatch, "NativeSemanticCoverageModel", compose)
    handoff = native_handoff(env)
    result = env.service.execute_claimed_session(handoff.lease, lease_ttl_seconds=300)
    assert checked and result.session.status is SessionStatus.COMPLETED
