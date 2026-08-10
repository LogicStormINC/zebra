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
    assert '"helm.sh/hook": pre-install,pre-upgrade' in migration
    assert "backoffLimit: 0" in migration
    assert "command: [python, docker/migrate.py]" in migration
    assert "readinessProbe:" in api and "livenessProbe:" in api and "startupProbe:" in api
    assert "command: [uvicorn]" in api
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
