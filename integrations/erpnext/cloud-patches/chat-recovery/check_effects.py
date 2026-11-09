"""Stdlib check of actual constructor/execute/schedule guards; native test is separate."""

import ast
from contextlib import nullcontext
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from source_projection import verify_source_projection

ROOT = Path(__file__).resolve().parent


def main():
    verify_source_projection(ROOT)
    for path in ROOT.rglob("*.py"):
        ast.parse(path.read_text())
    tree = ast.parse((ROOT / "tools/effect_guard.py").read_text())
    cls = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "FencedEffectToolGateway"
    )
    cls.body = [
        n
        for n in cls.body
        if isinstance(n, ast.FunctionDef) and n.name in {"__init__", "execute", "_schedule"}
    ]
    scope = dict(
        nullcontext=nullcontext,
        timedelta=timedelta,
        EffectDispatchStateError=ValueError,
        read_only_tool_names=lambda gateway: frozenset({"agent.plan", "files.read"}),
    )
    module = ast.Module(
        body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            cls,
        ],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), "<actual-fenced-guards>", "exec"), scope)
    Gateway = scope["FencedEffectToolGateway"]
    invoked = []
    gateway = SimpleNamespace(
        model_tools=(SimpleNamespace(name="agent.plan"),),
        execute=lambda call: invoked.append(call.name),
    )
    kwargs = dict(
        dispatch=None,
        artifacts=None,
        execution_session_id=None,
        root_session_id=None,
        fence=None,
        claim_ttl=timedelta(seconds=1),
        authority_scope="check",
        next_event=None,
        accept_event=None,
        ownership_check=lambda: None,
    )
    guarded = Gateway(gateway, payloadless_readonly=True, **kwargs)
    guarded.execute(SimpleNamespace(name="agent.plan"))
    assert invoked == ["agent.plan"]
    for name in ("files.read", "command.run", "unknown"):
        try:
            guarded.execute(SimpleNamespace(name=name))
        except ValueError:
            pass
        else:
            raise AssertionError("unknown/read-but-not-shown tool reached execution")
    try:
        guarded._schedule(SimpleNamespace(name="command.run"))
    except ValueError:
        pass
    else:
        raise AssertionError("payloadless Effect scheduling allowed")
    try:
        Gateway(gateway, **kwargs)
    except ValueError:
        pass
    else:
        raise AssertionError("default payload strategy requirement changed")
    assert invoked == ["agent.plan"]
    print(
        "PASS: actual readonly constructor/execute/schedule guards; defau"
        "lt payload requirement intact"
    )


if __name__ == "__main__":
    main()
