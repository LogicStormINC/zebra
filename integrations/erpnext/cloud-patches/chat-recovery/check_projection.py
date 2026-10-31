"""Actual targeted routing/cursor contract; no DB, lifecycle or provider calls."""

import ast
from pathlib import Path
from types import SimpleNamespace

from source_projection import verify_source_projection

ROOT = Path(__file__).resolve().parent


def main():
    verify_source_projection(ROOT)
    path = ROOT / "worker/erp_chat_readonly_main.py"
    tree = ast.parse(path.read_text())
    fn = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_chat_projection"
    )
    assert not any(
        isinstance(n, ast.Attribute)
        and n.attr
        in {
            "_repair_task",
            "backfill_projection_sources",
            "backfill_event_positions",
            "backfill_replay_headers",
        }
        for n in ast.walk(fn)
    )
    branch = next(
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.If) and "repair_projection_work(" in ast.unparse(n.test)
    )
    for incomplete in (False, True):
        calls, repaired = [], {}

        def routing(task_id, *, limit, calls=calls, incomplete=incomplete):
            calls.append((task_id, limit))
            return SimpleNamespace(needs_repair=incomplete)

        scope = dict(
            consumer=SimpleNamespace(work=SimpleNamespace(repair_projection_work=routing)),
            TaskId=lambda value: value,
            row={"task_id": "isolated-task", "next_event_sequence": 42},
            repaired=repaired,
            key=("consumer", "isolated-task"),
        )
        exec(
            compile(
                ast.Module(body=[branch], type_ignores=[]), "<actual-routing-frontier>", "exec"
            ),
            scope,
        )
        assert calls == [("isolated-task", 256)]
        assert repaired == ({} if incomplete else {("consumer", "isolated-task"): 42})
    source = path.read_text()
    assert (
        "consumer.materialize_once(work)" in source
        and "require_new_task(work.scope.task_id)" in source
    )
    assert any(
        ast.dump(n) == ast.dump(ast.parse("policy.require(row['session_id'])").body[0].value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
    )
    print(
        "PASS: incremental native routing only; incomplete routing retrie"
        "s; typed gate and checkpoints retained"
    )


if __name__ == "__main__":
    main()
