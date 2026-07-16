from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

SOURCE_LIMIT = 500
TEST_LIMIT = 700
SOURCE_SUFFIXES = frozenset({".py", ".ts", ".tsx"})
EXCLUDED_PARTS = frozenset(
    {
        ".cargo-home",
        ".git",
        ".mypy_cache",
        ".pnpm-store",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "build",
        "dist",
        "node_modules",
        "target",
    }
)
EXCLUDED_PREFIXES = ("UI/desktop/src-tauri/gen/",)


@dataclass(frozen=True, order=True)
class FileSizeViolation:
    path: str
    actual: int
    limit: int


def limit_for(path: str) -> int | None:
    normalized = PurePosixPath(path)
    if normalized.suffix not in SOURCE_SUFFIXES:
        return None
    if EXCLUDED_PARTS.intersection(normalized.parts):
        return None
    if path.startswith(EXCLUDED_PREFIXES):
        return None
    if _is_test_source(normalized):
        return TEST_LIMIT
    return SOURCE_LIMIT


def check_paths(root: Path, paths: tuple[str, ...]) -> tuple[int, tuple[FileSizeViolation, ...]]:
    checked = 0
    violations: list[FileSizeViolation] = []
    for relative_path in sorted(paths):
        limit = limit_for(relative_path)
        if limit is None:
            continue
        checked += 1
        actual = _line_count(root / relative_path)
        if actual > limit:
            violations.append(FileSizeViolation(relative_path, actual, limit))
    return checked, tuple(violations)


def tracked_paths(root: Path) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return tuple(
        path.decode("utf-8")
        for path in result.stdout.split(b"\0")
        if path
    )


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    checked, violations = check_paths(root, tracked_paths(root))
    print(
        "file size gate: "
        f"passed={not violations} checked={checked} violations={len(violations)}"
    )
    for violation in violations:
        print(
            f"- {violation.path}: actual={violation.actual} "
            f"limit={violation.limit}"
        )
    return 1 if violations else 0


def _is_test_source(path: PurePosixPath) -> bool:
    name = path.name
    return (
        "tests" in path.parts
        or "checks" in path.parts
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
        or ".check." in name
    )


def _line_count(path: Path) -> int:
    with path.open(encoding="utf-8") as source:
        return sum(1 for _ in source)


if __name__ == "__main__":
    raise SystemExit(main())
