import re
from pathlib import Path

from agent_context.scanner import ScannedFile


def recall_related_files(
    ranked_files: list[ScannedFile],
    *,
    limit: int = 4,
) -> list[ScannedFile]:
    index = {file.relative_path.as_posix(): file for file in ranked_files}
    module_index = _build_python_module_index(ranked_files)
    related: list[ScannedFile] = []
    seen: set[str] = set()
    for file in ranked_files[:3]:
        for candidate in _related_paths_for(file, module_index):
            key = candidate.as_posix()
            if key in seen:
                continue
            match = index.get(key)
            if match is None:
                continue
            related.append(match)
            seen.add(key)
            if len(related) >= limit:
                return related
    return related


def _related_paths_for(
    file: ScannedFile,
    module_index: dict[str, Path],
) -> list[Path]:
    if file.relative_path.suffix != ".py":
        return []
    modules = _extract_python_modules(file.content)
    return [path for module, path in module_index.items() if module in modules]


def _build_python_module_index(files: list[ScannedFile]) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for file in files:
        if file.relative_path.suffix != ".py":
            continue
        parts = list(file.relative_path.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            continue
        index[".".join(parts)] = file.relative_path
    return index


def _extract_python_modules(content: str) -> set[str]:
    modules: set[str] = set()
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("import "):
            imported = line.removeprefix("import ").split(",")
            for name in imported:
                module = name.strip().split(" as ", maxsplit=1)[0].strip()
                if module:
                    modules.add(module)
        if line.startswith("from "):
            match = re.match(r"from\s+([a-zA-Z0-9_\.]+)\s+import\s+", line)
            if match:
                modules.add(match.group(1))
    return modules
