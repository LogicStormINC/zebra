from pathlib import Path

ROOT = Path(__file__).parents[3]
RUNNER = ROOT / "tests/k8s/gvisor/run-e2e.sh"
WORKFLOW = ROOT / ".github/workflows/k8s-gvisor-e2e.yml"


def test_runner_is_fail_closed_and_cleans_namespace() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert "@sha256:" in source
    assert "runtimeclass gvisor" in source
    assert '"$RUNTIME_HANDLER" != "runsc"' in source
    assert "ResourceQuota" in source
    assert "NetworkPolicy" in source
    assert "allow-worker-api-egress" in source
    assert 'logs -n "$NAMESPACE" -l app=worker' in source
    assert "disable-network-policy" in source
    assert "WORKER_RESTART_RESUME=PASS" in source
    assert "delete namespace" in source
    assert "result.json" in source


def test_fixture_scripts_and_workflow_are_present() -> None:
    for name in ("api.py", "worker.py", "blocked_probe.py"):
        assert (RUNNER.parent / name).is_file()
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch" in workflow
    assert "self-hosted" in workflow
    assert "run-e2e.sh" in workflow
    assert "if-no-files-found: error" in workflow
