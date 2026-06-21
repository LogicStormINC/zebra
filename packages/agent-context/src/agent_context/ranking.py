import re
from pathlib import Path

from agent_context.scanner import PREFERRED_ROOT_FILES, ScannedFile


def rank_files(files: list[ScannedFile], task_input: str) -> list[ScannedFile]:
    return sorted(
        files,
        key=lambda file: (
            -score_file(file.relative_path, file.content, task_input),
            file.relative_path.as_posix(),
        ),
    )


def score_file(relative_path: Path, content: str, task_input: str) -> int:
    normalized_task_terms = {
        term
        for term in re.findall(r"[a-zA-Z0-9_./-]+", task_input.lower())
        if len(term) >= 3
    }
    score = 0
    path_text = relative_path.as_posix().lower()
    if relative_path.name in PREFERRED_ROOT_FILES:
        score += 40
    if "docs/" in path_text:
        score += 20
    for term in normalized_task_terms:
        if term in path_text:
            score += 25
        if term in content.lower():
            score += 10
    return score
