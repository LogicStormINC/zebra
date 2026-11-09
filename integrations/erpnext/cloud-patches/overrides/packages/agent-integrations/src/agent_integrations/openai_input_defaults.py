from __future__ import annotations

from pathlib import Path


def _read_defaults(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    defaults: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", maxsplit=1)
        defaults[key.strip()] = value.strip()
    return defaults


def _serialized_tool_name(tool: dict[str, object]) -> str:
    function = tool.get("function")
    if not isinstance(function, dict):
        return ""
    name = function.get("name")
    return name if isinstance(name, str) else ""
