"""Host-QA seam checks; no real containers, broker calls or application mutations."""

from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest
import run_acceptance
import support
from support import ConfigError, HttpResult
from test_runner import isolated_config as isolated_config_fixture

isolated_config = isolated_config_fixture


@pytest.fixture
def host_config(isolated_config, monkeypatch):
    config, rows, manifest = isolated_config
    manifest["containers"].pop("operator")
    rows[:] = [r for r in rows if not r["Name"].endswith("-operator")]
    Path(config.isolation_manifest).write_text(json.dumps(manifest))
    monkeypatch.setenv("ZEBRA_E2E_OPERATOR_MODE", "host")
    monkeypatch.setenv("ZEBRA_E2E_P1_FROZEN", "1")
    return config, rows, manifest


def test_explicit_frozen_host_does_not_require_phantom_operator_container(host_config):
    support.validate_isolation(host_config[0])


def test_default_sidecar_still_requires_its_pinned_operator(host_config, monkeypatch):
    monkeypatch.delenv("ZEBRA_E2E_OPERATOR_MODE")
    with pytest.raises(ConfigError):
        support.validate_isolation(host_config[0])


@pytest.mark.parametrize("mode,frozen", [("host", "0"), ("HOST", "1"), ("host ", "1")])
def test_nonexplicit_or_unfrozen_mode_never_reaches_native_or_http(
    isolated_config, monkeypatch, mode, frozen
):
    monkeypatch.setenv("ZEBRA_E2E_OPERATOR_MODE", mode)
    monkeypatch.setenv("ZEBRA_E2E_P1_FROZEN", frozen)
    calls = []
    monkeypatch.setattr("support.subprocess.run", lambda *_a, **_k: calls.append("docker"))
    monkeypatch.setattr("support.request", lambda *_a, **_k: calls.append("http"))
    with pytest.raises(ConfigError):
        support.obtain_grant(isolated_config[0], "trench-bootstrap-" + "a" * 32, "run")
    assert not calls


@pytest.mark.parametrize("defect", ["browser_worker", "namespace", "database", "network", "pin"])
def test_host_still_requires_exact_worker_namespace_native_route_and_pins(host_config, defect):
    config, rows, manifest = host_config
    worker = next(r for r in rows if r["Id"] == manifest["containers"]["worker"]["id"])
    if defect == "browser_worker":
        worker["Name"] = f"/{manifest['namespace_id']}-frontend"
    elif defect == "namespace":
        worker["Config"]["Env"][1] = "ZEBRA_DEPLOYMENT_NAMESPACE=application"
        manifest["containers"]["worker"]["config_sha256"] = sha256(
            json.dumps(worker["Config"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        Path(config.isolation_manifest).write_text(json.dumps(manifest))
    elif defect == "database":
        config = replace(config, zebra_database_dsn="postgresql://127.0.0.1:19008/application")
    elif defect == "network":
        worker["NetworkSettings"]["Networks"] = {"application-network": {}}
    else:
        worker["Config"]["Env"].append("RETARGETED=yes")
    with pytest.raises(ConfigError):
        support.validate_isolation(config)


def test_host_grant_uses_existing_real_exchange_contract_without_operator(host_config, monkeypatch):
    config = host_config[0]
    calls = []

    def transport(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return HttpResult(200, b'{"grant":"broker-result"}', {})

    monkeypatch.setattr("support.request", transport)
    thread = "trench-bootstrap-" + "a" * 32
    assert support.obtain_grant(config, thread, "run-1") == "broker-result"
    method, url, kwargs = calls[0]
    assert (method, url) == ("POST", config.grant_exchange_url)
    assert kwargs["payload"] == {
        "audience": "zebra",
        "scopes": list(support.HOST_GRANT_SCOPES),
        "threadId": thread,
        "runId": "run-1",
    }
    with pytest.raises(support.E2EError, match="host_thread"):
        support.obtain_grant(config, "task-uuid-not-host-thread", "run-1")
    assert len(calls) == 1


def test_host_snapshot_reuses_bounded_native_helper_never_placeholder_http(
    host_config, monkeypatch
):
    import joint_worker_takeover

    config = host_config[0]
    calls = []
    monkeypatch.setattr(
        joint_worker_takeover, "host_business_snapshot", lambda c: calls.append(c) or "digest"
    )
    monkeypatch.setattr(
        support, "request", lambda *_a, **_k: pytest.fail("unused sidecar URL called")
    )
    assert support.business_snapshot(config) == "digest"
    assert calls == [config]


def test_host_restart_reuses_exact_manifest_helper_without_http(host_config, monkeypatch):
    import joint_worker_takeover

    config = host_config[0]
    calls = []
    monkeypatch.setattr(
        joint_worker_takeover, "host_worker_restart", lambda *a: calls.append(a) or 204
    )
    monkeypatch.setattr(run_acceptance, "request", lambda *_a, **_k: pytest.fail("sidecar called"))
    run_acceptance.worker_restart(config, "task", "run")
    assert calls == [(config, "task", "run")]


@pytest.mark.parametrize("operation", ["snapshot", "restart"])
def test_unfrozen_host_never_dispatches_or_falls_back(isolated_config, monkeypatch, operation):
    import joint_worker_takeover

    monkeypatch.setenv("ZEBRA_E2E_OPERATOR_MODE", "host")
    monkeypatch.setenv("ZEBRA_E2E_P1_FROZEN", "0")

    def forbidden(*_a, **_k):
        pytest.fail("unfrozen host must not invoke a helper or HTTP")

    monkeypatch.setattr(joint_worker_takeover, "host_business_snapshot", forbidden)
    monkeypatch.setattr(joint_worker_takeover, "host_worker_restart", forbidden)
    monkeypatch.setattr(support, "request", forbidden)
    monkeypatch.setattr(run_acceptance, "request", forbidden)
    with pytest.raises(ConfigError):
        if operation == "snapshot":
            support.business_snapshot(isolated_config[0])
        else:
            run_acceptance.worker_restart(isolated_config[0], "task", "run")
