"""Stdlib regression of actual nullable-root guards and model-step opt-in."""
import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent


def main():
    manifest = ROOT / 'frozen-manifest.json'
    if manifest.exists():
        for name, digest in json.loads(manifest.read_bytes())['files'].items():
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
    for path in ROOT.rglob('*.py'):
        ast.parse(path.read_text())
    cls = next(n for n in ast.parse((ROOT / 'context/models.py').read_text()).body
        if isinstance(n, ast.ClassDef) and n.name == 'ContextCompileRequest')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '__post_init__')
    scope = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<actual-context-validation>', 'exec'), scope)
    value = SimpleNamespace(task_input='contract', workspace_root=None, include_workspace=False,
        runtime_evidence_items=(), memory_items=(), attachment_items=())
    scope['__post_init__'](value)
    value.include_workspace = True
    try:
        scope['__post_init__'](value)
    except ValueError:
        pass
    else:
        raise AssertionError('default missing workspace accepted')
    value.workspace_root = Path('relative-contract-root')
    for include in (False, True):
        value.include_workspace = include
        try:
            scope['__post_init__'](value)
        except ValueError:
            pass
        else:
            raise AssertionError('non-None existing path validation changed')
    tree = ast.parse((ROOT / 'core/harness/model_step.py').read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'build_initial_messages')
    condition = next(n.test for n in fn.body if isinstance(n, ast.If) and 'supports_workspace_free_context' in ast.unparse(n.test))
    task = SimpleNamespace(workspace_root=None)
    for compiler, expected in ((None, False), (object(), False),
            (SimpleNamespace(supports_workspace_free_context=True), True)):
        assert bool(eval(compile(ast.Expression(condition), '<actual-model-context-guard>', 'eval'),
            {'self': SimpleNamespace(_context_compiler=compiler), 'task': task})) == expected
    print('PASS: workspace-free explicit opt-in; default missing/relative root and compiler behavior preserved')


if __name__ == '__main__':
    main()
