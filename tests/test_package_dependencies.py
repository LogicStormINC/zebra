from pathlib import Path
from tomllib import loads


def test_workspace_package_dependencies_are_acyclic() -> None:
    packages_root = Path(__file__).parents[1] / "packages"
    graph: dict[str, set[str]] = {}
    for pyproject_path in packages_root.glob("*/pyproject.toml"):
        project = loads(pyproject_path.read_text(encoding="utf-8"))
        name = project["project"]["name"]
        sources = project.get("tool", {}).get("uv", {}).get("sources", {})
        graph[name] = set(sources)

    visited: set[str] = set()
    active: list[str] = []

    def visit(package: str) -> None:
        if package in active:
            cycle = " -> ".join((*active[active.index(package) :], package))
            raise AssertionError(f"workspace package dependency cycle: {cycle}")
        if package in visited:
            return
        active.append(package)
        for dependency in sorted(graph[package] & graph.keys()):
            visit(dependency)
        active.pop()
        visited.add(package)

    for package in sorted(graph):
        visit(package)
