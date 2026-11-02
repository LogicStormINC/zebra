"""A fresh proof reader must not load unrelated execution or object-storage backends."""

import os
import subprocess
import sys


def test_authority_reader_has_no_worker_loop_or_object_storage_bootstrap():
    code = """import sys
import zebra_agent_worker.host_authority_probe
assert 'zebra_agent_worker.loop' not in sys.modules, 'proof imports full Worker loop'
assert 'agent_integrations.deepseek_responses' not in sys.modules, 'proof imported model provider'
assert 'agent_storage.artifact_objects' not in sys.modules, 'proof imports unused object backend'
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_public_exports_keep_exact_original_object_identity():
    code = """import importlib
for name in ['zebra_agent_worker','agent_storage','agent_storage.postgres','agent_integrations']:
 module=importlib.import_module(name)
 original=importlib.import_module(name+'._public_exports')
 for symbol in original.__all__:
  assert getattr(module,symbol) is getattr(original,symbol),(name,symbol)
 assert set(original.__all__)<=set(dir(module))
 try:getattr(module,'absent_public_attribute')
 except AttributeError:pass
 else:raise AssertionError('missing name silently accepted')
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
