"""Prove entry wiring and actual TLS teardown, not cancellation of a waiter."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.tool_profiles import ToolProfile
from agent_runtime.crawl_gateway import CrawlGateway
from zebra_agent_worker.control import SessionControlService
from zebra_agent_worker.execution import SessionExecutionService
from zebra_agent_worker.execution_events import ExecutionInterrupted
from zebra_agent_worker.execution_tool_gateway import build_execution_tool_gateway, extensions

from tests.agent_runtime.test_crawl_source_http import call, native_tls_source
from tests.agent_runtime.test_native_network_cancellation import (
    native_connect_proxy,
    observe_children,
)
from tests.worker.execution.worker_execution_support import _settings
from tests.worker.test_cloud_context_materialization import _task
from tests.worker.test_execution_progress_entry import _entry
from tests.worker.test_recorder_append_guards import _recorder


def test_entry_cancellation_reports_durable_state_without_finalizing_stale_recorder(
    tmp_path,
    monkeypatch,
):
    service, claimed, stores, recorder, _, _, gateway, finished = _entry(tmp_path, monkeypatch)
    checks = []

    def compose(*_, network_cancellation_check=None, **__):
        checks.append(network_cancellation_check)
        return gateway

    monkeypatch.setattr(
        "zebra_agent_worker.execution.execution_gateway.build_execution_tool_gateway", compose
    )

    def run(*_, **__):
        assert len(checks) == 1 and callable(checks[0])
        checks[0]()
        control = SessionControlService(
            service._database_path, settings=service._settings, stores=stores
        )
        control.cancel_session(claimed.lease.session_id)
        assert recorder.session.status is SessionStatus.RUNNING  # Deliberately stale.
        with monkeypatch.context() as bounded:
            bounded.setattr(
                stores.events, "read_since", lambda *_: pytest.fail("control poll read history")
            )
            bounded.setattr(
                stores.events, "list_for_session", lambda *_: pytest.fail("control poll hydrated")
            )
            checks[0]()
        pytest.fail("cancellation must interrupt execution")

    monkeypatch.setattr("zebra_agent_worker.execution_completion.run_continuation", run)
    result = SessionExecutionService._execute_claimed_session_once(
        service, claimed, started_at=datetime.now(UTC), ownership_check=lambda: None
    )
    assert result.session == stores.sessions.get_session(claimed.lease.session_id)
    assert result.session.status is SessionStatus.CANCELLED
    assert result.attempt_result.metadata["external_status"] == "cancelled"
    finished.assert_not_called()
    gateway.close.assert_called_once()


@pytest.mark.parametrize("v2", [False, True])
@pytest.mark.parametrize("cause", ["cancel", "ownership_lost"])
def test_execution_gateway_stops_native_read_and_reaps_on_actual_control(
    tmp_path,
    monkeypatch,
    v2,
    cause,
):
    stores, recorder, session_id = _recorder(tmp_path)
    settings = replace(_settings(tmp_path / "recorder.sqlite"), web_pipeline_v2=v2)
    ownership = Mock()
    recorder._ownership_check = ownership
    service = SimpleNamespace(
        _settings=settings,
        _session_history=stores.session_history,
        _artifact_payload_store=None,
        _egress_registry=None,
        _delegation_store=None,
        _deployment_namespace=None,
        _frozen_manifest_loader=None,
        _client_runtime=None,
        _extensions=extensions(None, None),
    )
    children = observe_children(monkeypatch)
    monkeypatch.setattr(
        "agent_runtime.web_tools.CrawlGateway",
        partial(CrawlGateway, resolver=lambda _host: ("93.184.216.34",)),
    )
    with native_connect_proxy(monkeypatch) as target:
        with native_tls_source(tmp_path, monkeypatch, "drip", on_listen=target.append) as (
            requests,
            entered,
            closed,
            release,
            writes,
        ):
            gateway = build_execution_tool_gateway(
                service,
                task=replace(_task(tmp_path), tool_profile=ToolProfile.GENERAL),
                model_gateway=Mock(),
                session_id=session_id,
                runtime=Mock(),
                runtime_handle=Mock(),
                cloud_artifacts=None,
                trusted_local=True,
                task_binding=None,
                materialized_context=None,
                extension=None,
                fence=Mock(),
                network_cancellation_check=recorder.require_active_execution,
            )
            with ThreadPoolExecutor(max_workers=1) as executor:
                native = executor.submit(gateway.execute, call("web.fetch"))
                try:
                    assert entered.wait(2), (
                        native.result(timeout=1) if native.done() else "no request"
                    )
                    signal = LeaseLostError("actual lease fence lost")
                    if cause == "cancel":
                        SessionControlService(
                            tmp_path / "recorder.sqlite", settings=settings, stores=stores
                        ).cancel_session(session_id)
                    else:
                        ownership.side_effect = signal
                    expected = ExecutionInterrupted if cause == "cancel" else LeaseLostError
                    with pytest.raises(expected) as stopped:
                        native.result(timeout=1)
                    if cause == "cancel":
                        assert stopped.value.session.status is SessionStatus.CANCELLED
                    else:
                        assert stopped.value is signal
                    assert closed.wait(0.5) and not release.is_set()
                    assert len(requests) == 1 and writes
                    assert children and all(child.poll() is not None for child in children)
                    assert all(child.stdout.closed and child.stdin.closed for child in children)
                    previous = len(children)
                    with pytest.raises(expected) as repeated:
                        gateway.execute(call("web.fetch"))
                    assert repeated.value is stopped.value and len(children) == previous
                finally:
                    release.set()
                    gateway.close()
