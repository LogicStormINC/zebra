from dataclasses import dataclass
from pathlib import Path

from agent_context.models import ContextItem, ContextItemKind, ContextProvenance

TEXT_SUFFIXES = {".md", ".py", ".toml", ".yaml", ".yml", ".json"}
SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}
PREFERRED_ROOT_FILES = (
    "AGENTS.md",
    "README.md",
    "pyproject.toml",
    "Makefile",
)


@dataclass(frozen=True)
class ScannedFile:
    absolute_path: Path
    relative_path: Path
    content: str
    snippet: str


def scan_workspace_files(workspace_root: Path) -> list[ScannedFile]:
    discovered: list[Path] = []
    seen: set[Path] = set()
    preferred = [workspace_root / name for name in PREFERRED_ROOT_FILES]
    preferred.extend(sorted((workspace_root / "docs").glob("*.md")))
    for path in preferred:
        if path.is_file() and path not in seen:
            discovered.append(path)
            seen.add(path)
    for path in sorted(workspace_root.rglob("*")):
        if path in seen or not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix not in TEXT_SUFFIXES:
            continue
        discovered.append(path)
        seen.add(path)
    return [
        ScannedFile(
            absolute_path=path,
            relative_path=path.relative_to(workspace_root),
            content=_read_text(path),
            snippet=_normalize_snippet(_read_text(path)),
        )
        for path in discovered
    ]


def build_repo_map_item(workspace_root: Path) -> ContextItem:
    top_level = sorted(
        child.name
        for child in workspace_root.iterdir()
        if child.is_dir() and not child.name.startswith(".")
    )
    content = (
        f"workspace={workspace_root.name}\n"
        f"top_level_dirs={', '.join(top_level) if top_level else '(none)'}"
    )
    return ContextItem(
        kind=ContextItemKind.REPO_MAP,
        title="Repo Map",
        content=content,
        provenance=ContextProvenance(
            source_type="workspace",
            locator=str(workspace_root),
        ),
        priority=100,
        token_count=estimate_tokens(content),
    )


def estimate_tokens(content: str) -> int:
    return max(1, (len(content) + 3) // 4)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _normalize_snippet(content: str) -> str:
    lines = [line.rstrip() for line in content.splitlines()]
    compact = "\n".join(line for line in lines[:40] if line.strip())
    return compact[:1200].strip() or "(empty)"
