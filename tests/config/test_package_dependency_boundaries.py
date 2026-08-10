from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ROOT / "packages"

# These are the two known successor-task seams. Keeping the inventory exact
# means a new package-level configuration dependency fails this contract before
# ARCH-CONFIG-INTEGRATIONS-01 and ARCH-CONFIG-SECURITY-01 remove the entries.
KNOWN_CONFIG_IMPORTS = {
    "packages/agent-integrations/src/agent_integrations/deepseek_beta.py",
    "packages/agent-integrations/src/agent_integrations/openai_compatible.py",
    "packages/agent-integrations/src/agent_integrations/scm.py",
    "packages/agent-integrations/src/agent_integrations/scm_credentials.py",
    "packages/agent-security/src/agent_security/credentials.py",
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _package_sources() -> list[Path]:
    return sorted(PACKAGES.glob("*/src/**/*.py"))


def test_reusable_packages_do_not_import_apps_or_composition_roots() -> None:
    forbidden_prefixes = ("apps", "zebra_agent_api", "zebra_agent_worker")
    violations = {
        f"{path.relative_to(ROOT)}: {name}"
        for path in _package_sources()
        for name in _imports(path)
        if name == "apps" or name.startswith(forbidden_prefixes)
    }
    assert violations == set()


def test_provider_config_import_inventory_is_explicit() -> None:
    actual = {
        str(path.relative_to(ROOT))
        for path in _package_sources()
        if "zebra_agent_config" in _imports(path)
    }
    assert actual == KNOWN_CONFIG_IMPORTS
