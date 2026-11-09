"""Operator counters must reach the actual Cloud execution and delegation roots."""

import importlib
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest


@pytest.mark.parametrize("explicit", [False, True])
def test_cloud_bundle_counter_reaches_both_execution_paths(tmp_path, monkeypatch, explicit):
    from zebra_agent_worker.cloud_composition import compose_cloud_worker
    from zebra_agent_worker.loop import build_worker_loop_service

    from tests.test_cloud_api_worker_profile_composition import _cloud_settings
    from tests.worker.test_command_recovery import _settings

    monkeypatch.setattr("agent_storage.runtime_composition.require_current_schema", lambda _: None)
    def counter(gateway, assembly):
        return None

    def override(gateway, assembly):
        return None
    bundle = compose_cloud_worker(_cloud_settings())
    bundle = replace(bundle, model_request_budget_factory=counter)
    monkeypatch.setattr(
        "zebra_agent_worker.command_process_state.command_cutover_state", lambda *a, **kw: False
    )
    captured = {}
    orchestration = {}

    def execution(**kw):
        captured.update(kw)
        return Mock()

    def children(*args, **kw):
        orchestration.update(kw)
        return None, None

    monkeypatch.setattr("zebra_agent_worker.loop.SessionExecutionService", execution)
    monkeypatch.setattr(
        "zebra_agent_worker.orchestration_wakeup_hook.compose_orchestration", children
    )
    service = build_worker_loop_service(
        database_path=tmp_path / "unused", settings=_settings(), cloud_worker_composition=bundle,
        model_request_budget_factory=override if explicit else None,
    )
    service.drain()
    expected = override if explicit else counter
    assert captured["model_request_budget_factory"] is expected
    assert orchestration["model_request_budget_factory"] is expected


@pytest.mark.parametrize("cloud", [False, True])
def test_cli_preserves_local_client_but_cloud_uses_cancellable_native_io(monkeypatch, cloud):
    entry = importlib.import_module("zebra_agent_worker.main")
    settings = SimpleNamespace(
        deployment="cloud" if cloud else "local", web_egress_socks_endpoint=None,
        storage_authority="postgresql" if cloud else "sqlite", database_url="unused",
        command_delivery=SimpleNamespace(execution_slots=1),
    )
    result = SimpleNamespace(
        cycles_completed=1, idle_cycles=1, stop_reason="idle",
        executed_session_ids=(), skipped_session_ids=(),
    )
    service = Mock()
    service.run.return_value = result
    builder = Mock(return_value=service)
    monkeypatch.setattr(entry, "load_settings", lambda: settings)
    monkeypatch.setattr(entry, "postgres_pool_scope", lambda *a, **kw: nullcontext())
    monkeypatch.setattr(entry, "build_worker_loop_service", builder)
    assert entry.main(["--max-cycles", "1"]) == 0
    client = builder.call_args.kwargs["model_http_client"]
    assert client is None if cloud else isinstance(client, httpx.Client) and client.is_closed


def test_isolated_executor_keeps_native_transport_and_operator_bundle(monkeypatch):
    entry = importlib.import_module("zebra_agent_worker.session_process_child")
    settings = SimpleNamespace(
        deployment="cloud", storage_authority="postgresql", database_url="unused"
    )
    bundle = object()
    factory = Mock(return_value=bundle)
    module = SimpleNamespace(build=factory)
    builder = Mock()
    monkeypatch.setattr(entry.sys, "argv", ["worker-child", "--check"])
    monkeypatch.setenv("ZEBRA_SESSION_PROCESS_FACTORY", "trusted_operator:build")
    monkeypatch.setattr(entry, "load_settings", lambda: settings)
    monkeypatch.setattr(entry, "settings_digest", lambda _: "digest")
    monkeypatch.setattr(entry, "cloud_composition_from_environment", lambda: "cloud")
    monkeypatch.setattr(entry.importlib, "import_module", lambda _: module)
    monkeypatch.setattr(entry, "postgres_pool_scope", lambda *a, **kw: nullcontext())
    monkeypatch.setattr(entry, "build_worker_loop_service", builder)
    entry.main()
    factory.assert_called_once_with(settings, "cloud")
    assert builder.call_args.kwargs["cloud_worker_composition"] is bundle
    assert builder.call_args.kwargs["model_http_client"] is None


def test_cli_constructs_operator_bundle_inside_live_pool_scope(monkeypatch):
    entry = importlib.import_module("zebra_agent_worker.main")
    settings = SimpleNamespace(
        deployment="cloud", web_egress_socks_endpoint=None,
        storage_authority="postgresql", database_url="unused",
        command_delivery=SimpleNamespace(execution_slots=1),
    )
    service = Mock()
    service.run.return_value = SimpleNamespace(
        cycles_completed=1, idle_cycles=1, stop_reason="idle",
        executed_session_ids=(), skipped_session_ids=(),
    )
    builder = Mock(return_value=service)
    bundle = object()
    monkeypatch.setattr(entry, "load_settings", lambda: settings)
    monkeypatch.setattr(entry, "postgres_pool_scope", lambda *a, **kw: nullcontext())
    monkeypatch.setattr(entry, "build_worker_loop_service", builder)
    active = []

    @contextmanager
    def pool(*args, **kw):
        active.append(True)
        try:
            yield
        finally:
            active.pop()

    def factory(actual):
        assert actual is settings and active == [True]
        return bundle

    monkeypatch.setattr(entry, "postgres_pool_scope", pool)
    assert entry.main(["--max-cycles", "1"], cloud_worker_composition_factory=factory) == 0
    assert active == []
    assert builder.call_args.kwargs["cloud_worker_composition"] is bundle
    assert builder.call_args.kwargs["model_http_client"] is None
