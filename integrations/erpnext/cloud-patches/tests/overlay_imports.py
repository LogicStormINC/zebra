"""Load exact override modules over an installed native dependency workspace."""
import importlib.abc
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PREFIXES = {name: ROOT / 'overrides' / path for name, path in {
    'agent_runtime': 'packages/agent-runtime/src/agent_runtime',
    'agent_tools': 'packages/agent-tools/src/agent_tools',
    'agent_integrations': 'packages/agent-integrations/src/agent_integrations',
    'agent_core': 'packages/agent-core/src/agent_core',
    'agent_storage': 'packages/agent-storage/src/agent_storage',
    'agent_security': 'packages/agent-security/src/agent_security',
    'zebra_agent_api': 'apps/api/src/zebra_agent_api',
    'zebra_agent_worker': 'apps/worker/src/zebra_agent_worker',
}.items()}

class Overrides(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        head, *tail = fullname.split('.')
        root = PREFIXES.get(head)
        if root is not None and tail:
            source = root.joinpath(*tail).with_suffix('.py')
            if source.is_file():
                return importlib.util.spec_from_file_location(fullname, source)
        return None

sys.meta_path.insert(0, Overrides())
