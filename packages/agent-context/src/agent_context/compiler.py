from pathlib import Path

from agent_context.models import (
    CompiledContext,
    ContextBudget,
    ContextCompileRequest,
    ContextItem,
    ContextItemKind,
    ContextProvenance,
)
from agent_context.ranking import rank_files, score_file
from agent_context.related import recall_related_files
from agent_context.scanner import (
    ScannedFile,
    build_repo_map_item,
    estimate_tokens,
    scan_workspace_files,
)
from agent_context.trust import prompt_injection_metadata, trust_level_for_item


def compile_context(
    request: ContextCompileRequest | None = None,
) -> CompiledContext:
    compile_request = request or ContextCompileRequest(
        task_input="bootstrap workspace context",
        workspace_root=Path.cwd().resolve(),
        budget=ContextBudget(max_tokens=200),
    )
    workspace_root = compile_request.workspace_root
    scanned_files = scan_workspace_files(workspace_root)
    ranked_files = rank_files(scanned_files, compile_request.task_input)
    ranked_items = [build_repo_map_item(workspace_root)]
    ranked_items.extend(compile_request.memory_items)
    ranked_items.extend(compile_request.attachment_items)
    ranked_items.extend(compile_request.runtime_evidence_items)
    ranked_items.extend(
        _build_file_item(
            file,
            task_input=compile_request.task_input,
            kind=ContextItemKind.FILE_SNIPPET,
        )
        for file in ranked_files
    )
    ranked_items.extend(
        _build_file_item(
            file,
            task_input=compile_request.task_input,
            kind=ContextItemKind.RELATED_FILE,
            priority_offset=5,
        )
        for file in recall_related_files(ranked_files)
    )
    ranked_items.sort(key=lambda item: (-item.priority, item.provenance.locator))
    return _apply_budget(ranked_items, compile_request.budget)


def _build_file_item(
    file: ScannedFile,
    *,
    task_input: str,
    kind: ContextItemKind,
    priority_offset: int = 0,
) -> ContextItem:
    priority = score_file(file.relative_path, file.content, task_input) + priority_offset
    return ContextItem(
        kind=kind,
        title=file.relative_path.as_posix(),
        content=file.snippet,
        provenance=ContextProvenance(
            source_type="file",
            locator=file.relative_path.as_posix(),
        ),
        trust_level=trust_level_for_item(
            kind=kind,
            locator=file.relative_path.as_posix(),
        ),
        priority=priority,
        token_count=estimate_tokens(file.snippet),
        metadata=prompt_injection_metadata(
            file.snippet,
            file.relative_path.as_posix(),
        ),
    )


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
