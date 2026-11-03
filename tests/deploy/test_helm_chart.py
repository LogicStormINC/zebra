from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[2]
CHART = ROOT / "deploy" / "helm" / "zebra-agent"
TEMPLATES = CHART / "templates"


def _read(path: str) -> str:
    return (TEMPLATES / path).read_text(encoding="utf-8")


def test_chart_inventory_and_schema_are_present() -> None:
    assert (CHART / "Chart.yaml").is_file()
    assert (CHART / "values.yaml").is_file()
    schema = json.loads((CHART / "values.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["profile"]["enum"] == ["cloud", "production"]
    assert schema["properties"]["runtimeClassName"]["const"] == "gvisor"
    assert schema["properties"]["workspaceQuota"]["properties"]["enabled"]["const"] is True
    assert schema["properties"]["image"]["properties"]["digest"]["pattern"] == (
        "^sha256:[0-9a-f]{64}$"
    )
    assert set(
        [
            "migration-job.yaml",
            "api-deployment.yaml",
            "worker-deployment.yaml",
            "service.yaml",
            "api-pdb.yaml",
            "worker-pdb.yaml",
            "serviceaccount.yaml",
            "_helpers.tpl",
        ]
    ).issubset({path.name for path in TEMPLATES.iterdir()})


def test_workloads_use_digest_runtime_and_least_privilege() -> None:
    for path in ("migration-job.yaml", "api-deployment.yaml", "worker-deployment.yaml"):
        text = _read(path)
        assert 'include "zebra-agent.image"' in text
        assert "runtimeClassName:" in text
        assert "runAsNonRoot: true" in _read("_helpers.tpl")
        assert "readOnlyRootFilesystem: true" in _read("_helpers.tpl")
        assert "allowPrivilegeEscalation: false" in _read("_helpers.tpl")
        assert "drop: [ALL]" in _read("_helpers.tpl")
        assert "include \"zebra-agent.cloudEnv\"" in text


def test_migration_api_worker_and_service_boundaries_are_explicit() -> None:
    migration = _read("migration-job.yaml")
    api = _read("api-deployment.yaml")
    worker = _read("worker-deployment.yaml")
    service = _read("service.yaml")
    service_account = _read("serviceaccount.yaml")
    assert '"helm.sh/hook": pre-install,pre-upgrade' in migration
    assert '"helm.sh/hook": pre-install,pre-upgrade' in service_account
    assert '"helm.sh/hook-weight": "-20"' in service_account
    assert "backoffLimit: 0" in migration
    assert "command: [python, docker/migrate.py]" in migration
    assert "readinessProbe:" in api and "livenessProbe:" in api and "startupProbe:" in api
    assert "command: [python, -m, zebra_agent_api.server]" in api
    assert "command: [zebra-agent-worker]" in worker
    assert "containerPort: 8000" in api
    assert "targetPort: http" in service
    assert "app.kubernetes.io/component: api" in service


def test_pdbs_and_templates_never_embed_secret_values() -> None:
    for path in ("api-pdb.yaml", "worker-pdb.yaml"):
        assert "kind: PodDisruptionBudget" in _read(path)
        assert "minAvailable: 1" in _read(path)
    template_text = "\n".join(path.read_text(encoding="utf-8") for path in TEMPLATES.iterdir())
    assert "value: zebra" not in template_text
    assert "POSTGRES_PASSWORD" not in template_text
    assert "stringData:" not in template_text
    assert "secretKeyRef:" in template_text


def test_budget_profiles_cover_rollout_and_private_executors():
    helper = _read("_helpers.tpl")
    assert "ZEBRA_DATABASE_BUDGET_JSON" in helper
    assert 'omit .Values.databaseBudget "enabled"' in helper
    assert "database budget omits rollout peaks" in helper
    for path in ("api-deployment.yaml", "worker-deployment.yaml"):
        assert "maxSurge: 1" in _read(path)


def test_budget_mode_is_install_only_and_counts_terminating_overlap(tmp_path):
    import shutil
    import subprocess

    import pytest

    if shutil.which("helm") is None:
        pytest.skip("Helm CLI required for real render acceptance")
    values = {
        "image": {"digest": "sha256:" + "a" * 64},
        "deploymentNamespace": "ha-review", "runtimeImage": "runtime@sha256:" + "b" * 64,
        "secrets": {name: {"name": "fixture-secret"} for name in
                    ["databaseUrl", "s3", "liveRedisUrl", "memorySigningKey", "apiAuthToken"]},
        "config": {"authorityIssuer": "https://issuer.example", "historyScopeNamespace": "history",
                   "continuationScopeNamespace": "continuation", "s3Endpoint": "https://s3.example"},
    }
    for enabled, upgrade, bad_peak, expected in [
        (True, False, False, 0), (True, True, False, 1),
        (False, True, False, 0), (True, False, True, 1),
    ]:
        values["databaseBudget"] = {"enabled": enabled}
        if bad_peak:
            values["databaseBudget"]["fleet"] = {"worker": 3}
        path = tmp_path / "values.json"
        path.write_text(json.dumps(values))
        result = subprocess.run(
            ["helm", "template", "ha-review", str(CHART), "-f", str(path)]
            + (["--is-upgrade"] if upgrade else []),
            capture_output=True, text=True, check=False,
        )
        assert (result.returncode == 0) == (expected == 0), result.stderr
        if enabled and upgrade:
            assert "budget-enabled upgrades" in result.stderr
        if bad_peak:
            assert "terminating overlap" in result.stderr

    for maximum in (257, 256):
        values["databaseBudget"] = {
            "enabled": True,
            "max_connections": maximum,
            "executor_limits": dict(pool=1, normal=1, read=1, control=1, probe=1),
        }
        path.write_text(json.dumps(values))
        result = subprocess.run(
            ["helm", "template", "ha-review", str(CHART), "-f", str(path)],
            capture_output=True, text=True, check=False,
        )
        if maximum == 257:
            assert result.returncode == 0, result.stderr
            assert "executor_limits" in result.stdout
        else:
            assert result.returncode != 0
            assert "database fleet exceeds server connection budget" in result.stderr
