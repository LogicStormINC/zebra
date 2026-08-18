"""Host write effect tests: uncertain recording and bounded reconciliation."""

from __future__ import annotations

import pytest
from agent_core.domain.host_connectors import HostConnectorProfileVersion
from agent_core.domain.host_effect_receipts import HostEffectStatus
from zebra_agent_worker.host_effect import (
    HostEffectReconciler,
    record_uncertain_write,
    settle_write,
)


def _profile(reconcile: str | None = "/tools/reconcile") -> HostConnectorProfileVersion:
    return HostConnectorProfileVersion(
        host_app_id="host-a",
        connector_id="host-a-main",
        profile_revision=1,
        base_uri="https://host-a.example.com",
        manifest_path="/manifest",
        invoke_path_template="/tools/invoke",
        reconcile_path_template=reconcile,
        supported_protocol_versions=("host-capability-protocol/1",),
        workload_identity_ref="workload/zebra-worker",
        credential_ref="credentials/host-a",
    )


class FakeTransport:
    def __init__(self, result: tuple[int, dict] | Exception) -> None:
        self._result = result
        self.calls: list[str] = []

    def request(self, url, *, provider_operation_id, timeout_seconds):
        self.calls.append(provider_operation_id)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class TestUncertainWrites:
    def test_timeout_records_uncertain_with_provider_operation_id(self) -> None:
        outcome = record_uncertain_write("host-write-42")
        assert outcome.receipt.effect_status is HostEffectStatus.UNCERTAIN
        assert outcome.receipt.provider_operation_id == "host-write-42"
        assert not outcome.receipt.reconciled
        assert outcome.attempts == 1

    def test_provider_operation_id_is_bounded(self) -> None:
        with pytest.raises(ValueError):
            record_uncertain_write("  ")
        with pytest.raises(ValueError):
            record_uncertain_write("x" * 257)

    def test_deterministic_outcomes_require_business_revision(self) -> None:
        with pytest.raises(ValueError):
            settle_write("op-1", succeeded=True, business_revision=None)
        settled = settle_write("op-2", succeeded=True, business_revision="rev-9")
        assert settled.receipt.effect_status is HostEffectStatus.SUCCEEDED
        failed = settle_write("op-3", succeeded=False, business_revision=None)
        assert failed.receipt.effect_status is HostEffectStatus.FAILED_NO_EFFECT


class TestReconciliation:
    def test_reconcile_settles_succeeded_with_business_revision(self) -> None:
        transport = FakeTransport((200, {"effectStatus": "succeeded", "businessRevision": "rev-1"}))
        reconciler = HostEffectReconciler(transport)
        uncertain = record_uncertain_write("op-9").receipt
        settled = reconciler.reconcile(_profile(), uncertain)
        assert settled.effect_status is HostEffectStatus.SUCCEEDED
        assert settled.business_revision == "rev-1"
        assert settled.reconciled

    def test_reconcile_settles_failed_no_effect(self) -> None:
        transport = FakeTransport((200, {"effectStatus": "failed_no_effect"}))
        reconciler = HostEffectReconciler(transport)
        uncertain = record_uncertain_write("op-10").receipt
        settled = reconciler.reconcile(_profile(), uncertain)
        assert settled.effect_status is HostEffectStatus.FAILED_NO_EFFECT

    def test_transport_failure_keeps_uncertain_no_blind_retry(self) -> None:
        transport = FakeTransport(ConnectionError("reconcile endpoint down"))
        reconciler = HostEffectReconciler(transport)
        uncertain = record_uncertain_write("op-11").receipt
        settled = reconciler.reconcile(_profile(), uncertain)
        assert settled.effect_status is HostEffectStatus.UNCERTAIN
        assert len(transport.calls) == 1

    def test_unknown_status_words_stay_uncertain(self) -> None:
        transport = FakeTransport((200, {"effectStatus": "maybe"}))
        reconciler = HostEffectReconciler(transport)
        uncertain = record_uncertain_write("op-12").receipt
        settled = reconciler.reconcile(_profile(), uncertain)
        assert settled.effect_status is HostEffectStatus.UNCERTAIN

    def test_http_error_keeps_uncertain(self) -> None:
        transport = FakeTransport((503, {}))
        reconciler = HostEffectReconciler(transport)
        uncertain = record_uncertain_write("op-13").receipt
        settled = reconciler.reconcile(_profile(), uncertain)
        assert settled.effect_status is HostEffectStatus.UNCERTAIN

    def test_profile_without_reconcile_path_never_calls_out(self) -> None:
        transport = FakeTransport((200, {"effectStatus": "succeeded"}))
        reconciler = HostEffectReconciler(transport)
        uncertain = record_uncertain_write("op-14").receipt
        settled = reconciler.reconcile(_profile(reconcile=None), uncertain)
        assert settled.effect_status is HostEffectStatus.UNCERTAIN
        assert transport.calls == []

    def test_settled_receipts_are_not_reconciled_again(self) -> None:
        transport = FakeTransport((200, {"effectStatus": "failed_no_effect"}))
        reconciler = HostEffectReconciler(transport)
        settled = settle_write("op-15", succeeded=True, business_revision="rev-2").receipt
        again = reconciler.reconcile(_profile(), settled)
        assert again.effect_status is HostEffectStatus.SUCCEEDED
        assert transport.calls == []
