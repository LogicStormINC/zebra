import re
from pathlib import Path

from agent_context.models import (
    CompiledContext,
    ContextBudget,
    ContextCompileRequest,
    ContextItem,
    ContextItemKind,
    ContextProvenance,
)

_TEXT_SUFFIXES = {".md", ".py", ".toml", ".yaml", ".yml", ".json"}
_SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}
_PREFERRED_ROOT_FILES = (
    "AGENTS.md",
    "README.md",
    "pyproject.toml",
    "Makefile",
)


def compile_context(
    request: ContextCompileRequest | None = None,
) -> CompiledContext:
    compile_request = request or ContextCompileRequest(
        task_input="bootstrap workspace context",
        workspace_root=Path.cwd().resolve(),
        budget=ContextBudget(max_tokens=200),
    )
    workspace_root = compile_request.workspace_root
    candidates = _scan_candidate_files(workspace_root)
    ranked_items = [_build_repo_map_item(workspace_root)]
    ranked_items.extend(
        sorted(
            (
                _build_file_item(path, workspace_root, compile_request.task_input)
                for path in candidates
            ),
            key=lambda item: (-item.priority, item.provenance.locator),
        )
    )
    return _apply_budget(ranked_items, compile_request.budget)


def _scan_candidate_files(workspace_root: Path) -> list[Path]:
    preferred = [workspace_root / name for name in _PREFERRED_ROOT_FILES]
    preferred.extend(sorted((workspace_root / "docs").glob("*.md")))
    discovered: list[Path] = []
    seen: set[Path] = set()
    for path in preferred:
        if path.is_file() and path not in seen:
            discovered.append(path)
            seen.add(path)
    for path in sorted(workspace_root.rglob("*")):
        if path in seen or not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.suffix not in _TEXT_SUFFIXES:
            continue
        discovered.append(path)
        seen.add(path)
    return discovered


def _build_repo_map_item(workspace_root: Path) -> ContextItem:
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
        token_count=_estimate_tokens(content),
    )


def _build_file_item(
    path: Path,
    workspace_root: Path,
    task_input: str,
) -> ContextItem:
    content = path.read_text(encoding="utf-8", errors="ignore")
    snippet = _normalize_snippet(content)
    relative_path = path.relative_to(workspace_root)
    priority = _score_path(relative_path, content, task_input)
    return ContextItem(
        kind=ContextItemKind.FILE_SNIPPET,
        title=relative_path.as_posix(),
        content=snippet,
        provenance=ContextProvenance(
            source_type="file",
            locator=relative_path.as_posix(),
        ),
        priority=priority,
        token_count=_estimate_tokens(snippet),
    )


def _score_path(relative_path: Path, content: str, task_input: str) -> int:
    normalized_task_terms = {
        term for term in re.findall(r"[a-zA-Z0-9_./-]+", task_input.lower()) if len(term) >= 3
    }
    score = 0
    path_text = relative_path.as_posix().lower()
    if relative_path.name in _PREFERRED_ROOT_FILES:
        score += 40
    if "docs/" in path_text:
        score += 20
    for term in normalized_task_terms:
        if term in path_text:
            score += 25
        if term in content.lower():
            score += 10
    return score


def _normalize_snippet(content: str) -> str:
    lines = [line.rstrip() for line in content.splitlines()]
    compact = "\n".join(line for line in lines[:40] if line.strip())
    return compact[:1200].strip() or "(empty)"


def _apply_budget(
    items: list[ContextItem],
    budget: ContextBudget,
) -> CompiledContext:
    selected: list[ContextItem] = []
    used_tokens = 0
    truncated = False
    for item in items:
        if used_tokens + item.token_count > budget.max_tokens:
            truncated = True
            continue
        selected.append(item)
        used_tokens += item.token_count
    return CompiledContext(
        items=tuple(selected),
        total_tokens=used_tokens,
        truncated=truncated,
    )


def _estimate_tokens(content: str) -> int:
    return max(1, (len(content) + 3) // 4)
