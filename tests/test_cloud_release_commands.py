import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_makefile_exposes_every_classified_cloud_gate() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    for target in (
        "test-cloud-contracts",
        "test-cloud-composition",
        "test-cloud-integration",
        "test-cloud-faults",
        "test-trench-e2e",
        "test-gvisor-runtime",
        "test-redis-agent-memory",
        "release-evidence",
    ):
        assert f"{target}:" in makefile


def test_release_gate_inventory_covers_l1_through_l6() -> None:
    config = json.loads(
        (ROOT / "configs/cloud_release_gates.json").read_text(encoding="utf-8")
    )
    assert config["schema_version"] == "zebra.cloud-release-gates.v1"
    assert {gate["level"] for gate in config["gates"]} == {
        "L1",
        "L2",
        "L3",
        "L4",
        "L5",
        "L6",
    }
    integration = next(gate for gate in config["gates"] if gate["id"] == "cloud-integration")
    assert len(integration["members"]) == 5


def test_ci_runs_classified_fault_performance_and_trench_gates() -> None:
    quality = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    trench = (ROOT / ".github/workflows/trench-e2e.yml").read_text(encoding="utf-8")
    assert "classified-cloud-gates:" in quality
    assert "cloud-faults:" in quality
    assert "performance-baseline:" in quality
    assert "make test-gvisor-runtime" in quality
    assert "make test-trench-e2e" in trench
    assert "continue-on-error" not in quality + trench
