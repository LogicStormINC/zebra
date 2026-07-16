import importlib.util
import sys
from pathlib import Path
from types import ModuleType

CHECKER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_file_sizes.py"


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_file_sizes", CHECKER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load file size checker")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def test_limit_for_classifies_source_tests_and_explicit_exclusions() -> None:
    assert checker.limit_for("apps/api/src/zebra_agent_api/app.py") == checker.SOURCE_LIMIT
    assert checker.limit_for("UI/desktop/src/App.tsx") == checker.SOURCE_LIMIT
    assert checker.limit_for("tests/api/test_app.py") == checker.TEST_LIMIT
    assert checker.limit_for("UI/desktop/checks/runtime.check.ts") == checker.TEST_LIMIT
    assert checker.limit_for("UI/desktop/src/App.test.tsx") == checker.TEST_LIMIT
    assert checker.limit_for("docs/architecture.md") is None
    assert checker.limit_for("UI/desktop/node_modules/library/index.ts") is None
    assert checker.limit_for("UI/desktop/src-tauri/gen/schema.ts") is None


def test_check_paths_reports_every_violation_in_stable_path_order(tmp_path: Path) -> None:
    paths = (
        "tests/test_large.py",
        "apps/example/src/large.py",
        "apps/example/src/small.py",
    )
    _write_lines(tmp_path / paths[0], checker.TEST_LIMIT + 1)
    _write_lines(tmp_path / paths[1], checker.SOURCE_LIMIT + 2)
    _write_lines(tmp_path / paths[2], checker.SOURCE_LIMIT)

    checked, violations = checker.check_paths(tmp_path, paths)

    assert checked == 3
    assert [(item.path, item.actual, item.limit) for item in violations] == [
        ("apps/example/src/large.py", checker.SOURCE_LIMIT + 2, checker.SOURCE_LIMIT),
        ("tests/test_large.py", checker.TEST_LIMIT + 1, checker.TEST_LIMIT),
    ]


def test_repository_file_size_gate_passes() -> None:
    root = Path(__file__).resolve().parents[1]
    tracked = checker.tracked_paths(root)

    _, violations = checker.check_paths(root, tracked)

    assert violations == ()


def _write_lines(path: Path, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("line\n" * count, encoding="utf-8")
