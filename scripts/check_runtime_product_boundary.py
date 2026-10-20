"""Check default Runtime ownership; explicit historical adapters remain supported."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_MESSAGES = {"trench.ai.turn.ready", "trench.source.fetch.ready", "trench_turn"}
# These values decode immutable v1 history; they are not defaults for new products.
HISTORICAL_LITERALS = {
    "packages/agent-core/src/agent_core/domain/coverage_contracts.py": {"trench.subscribed_events"},
    "packages/agent-core/src/agent_core/domain/coverage_legacy_source.py": {"trench.history"},
}
DEFAULT_FILES = (
    "docker/Dockerfile",
    "scripts/register_host.py",
    "apps/host_grant_broker/src/zebra_host_grant_broker/keys.py",
    "apps/scheduler/src/zebra_agent_scheduler/config.py",
    "docker/compose.application.yml",
    "docker/compose.local-gvisor.yml",
    "docker/.env.application.example",
    "configs/cloud_rollout_candidate.example.json",
)


def violations(root: Path = ROOT) -> list[str]:
    errors = []
    for directory in (root / "packages", root / "apps"):
        for path in directory.glob("*/src/**/*.py"):
            relative = path.relative_to(root).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [item.name for item in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                if any(
                    name.split(".")[0] == "trench" or name.split(".")[0].startswith("trench_")
                    for name in names
                ):
                    errors.append(f"{relative}:{node.lineno}: product implementation import")
                if (
                    relative.startswith("packages/agent-core/")
                    and isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value.startswith("trench.")
                    and node.value not in HISTORICAL_LITERALS.get(relative, set())
                ):
                    errors.append(f"{relative}:{node.lineno}: product literal in Core")
                if (
                    relative == "packages/agent-core/src/agent_core/contracts/broker_envelope.py"
                    and isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value in PRODUCT_MESSAGES
                ):
                    errors.append(f"{relative}:{node.lineno}: product broker message")
    for relative in DEFAULT_FILES:
        if "trench" in (root / relative).read_text(encoding="utf-8").lower():
            errors.append(f"{relative}: product dependency in default deployment")
    return sorted(set(errors))


def main() -> int:
    errors = violations()
    for error in errors:
        print(error)
    print(f"Runtime product boundary: {'FAIL' if errors else 'PASS'}")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
