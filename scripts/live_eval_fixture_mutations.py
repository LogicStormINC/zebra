# ruff: noqa: E501 -- executable fixture strings remain literal and independently hashable.

from __future__ import annotations

from typing import NamedTuple


class MutationFixture(NamedTuple):
    files: dict[str, str]
    instructions: str
    required_terms: tuple[str, ...]
    validation: tuple[str, ...]


def _python_case(source: str, test: str, terms: tuple[str, ...]) -> MutationFixture:
    return MutationFixture(
        {"subject.py": source, "test_subject.py": test, "unrelated.txt": "preserve-me\n"},
        "Fix the shared root cause in subject.py, preserve unrelated.txt, run python -m unittest -v, and report the exact validation result.",
        terms,
        ("python-tests", "preserve-unrelated"),
    )


def _file_case(source_name: str, source: str, target: str, instructions: str, terms: tuple[str, ...]) -> MutationFixture:
    return MutationFixture({source_name: source}, f"{instructions} Create {target}, then publish it with files.publish.", terms, (target,))


def _operation_case(state: str, script: str, instructions: str, terms: tuple[str, ...]) -> MutationFixture:
    return MutationFixture({"state.json": state, "apply.py": script}, instructions, terms, ("operation-state",))


def _memory_case(files: dict[str, str], instructions: str, terms: tuple[str, ...]) -> MutationFixture:
    return MutationFixture(
        files,
        f"{instructions} Write memory-result.json with selected_scope, selected_preference, excluded_scopes, replayed=false and writes=1, then independently read it back. This local fixture requires a verified workspace result, not Artifact publication.",
        terms,
        ("memory-result.json",),
    )


MUTATION_CASES = {
    "code-typescript-contract": _python_case(
        "def decode(payload):\n    return {'legacy_name': payload.get('name')}\n",
        "import unittest\nfrom subject import decode\nclass T(unittest.TestCase):\n def test_legacy_and_current(self):\n  self.assertEqual(decode({'name':'a','display_name':'b'}), {'legacy_name':'a','display_name':'b'})\nif __name__=='__main__': unittest.main()\n",
        ("legacy_name", "display_name", "unittest"),
    ),
    "code-state-machine": _python_case(
        "TERMINAL={'completed','failed'}\ndef transition(current,target):\n    return target\n",
        "import unittest\nfrom subject import transition\nclass T(unittest.TestCase):\n def test_terminal_is_final(self):\n  with self.assertRaises(ValueError): transition('completed','running')\n def test_active_can_finish(self): self.assertEqual(transition('running','completed'),'completed')\nif __name__=='__main__': unittest.main()\n",
        ("terminal", "ValueError", "unittest"),
    ),
    "code-idempotency": _python_case(
        "def apply(state,key):\n    state['writes'] += 1\n    state['keys'].append(key)\n    return state\n",
        "import unittest\nfrom subject import apply\nclass T(unittest.TestCase):\n def test_retry_once(self):\n  state={'writes':0,'keys':[]}\n  apply(state,'k'); apply(state,'k')\n  self.assertEqual(state,{'writes':1,'keys':['k']})\nif __name__=='__main__': unittest.main()\n",
        ("idempotency", "writes", "unittest"),
    ),
    "code-concurrency-race": _python_case(
        "import threading\n_value=0\ndef increment():\n global _value\n current=_value\n _value=current+1\ndef value(): return _value\n",
        "import unittest, threading, subject\nclass T(unittest.TestCase):\n def test_parallel(self):\n  self.assertTrue(hasattr(subject,'_lock'))\n  threads=[threading.Thread(target=subject.increment) for _ in range(100)]\n  [t.start() for t in threads]; [t.join() for t in threads]\n  self.assertEqual(subject.value(),100)\nif __name__=='__main__': unittest.main()\n",
        ("lock", "100", "unittest"),
    ),
    "code-migration-compat": _python_case(
        "def read(row):\n    return row['new_status']\n",
        "import unittest\nfrom subject import read\nclass T(unittest.TestCase):\n def test_old_and_new(self):\n  self.assertEqual(read({'status':'ready'}),'ready')\n  self.assertEqual(read({'status':'old','new_status':'done'}),'done')\nif __name__=='__main__': unittest.main()\n",
        ("new_status", "backward", "unittest"),
    ),
    "code-event-ordering": _python_case(
        "def append(last,sequence): return sequence\n",
        "import unittest\nfrom subject import append\nclass T(unittest.TestCase):\n def test_monotonic(self):\n  self.assertEqual(append(4,5),5)\n  with self.assertRaises(ValueError): append(5,5)\nif __name__=='__main__': unittest.main()\n",
        ("monotonic", "ValueError", "unittest"),
    ),
    "code-cache-key": _python_case(
        "def cache_key(tenant,model,prompt): return prompt\n",
        "import unittest\nfrom subject import cache_key\nclass T(unittest.TestCase):\n def test_identity(self):\n  self.assertNotEqual(cache_key('a','m','p'),cache_key('b','m','p'))\n  self.assertNotEqual(cache_key('a','m','p'),cache_key('a','n','p'))\nif __name__=='__main__': unittest.main()\n",
        ("tenant", "model", "unittest"),
    ),
    "code-package-boundary": _python_case(
        "from infrastructure import database\ndef total(values): return sum(values)\n",
        "import ast, unittest\nfrom pathlib import Path\nclass T(unittest.TestCase):\n def test_core_has_no_infrastructure_import(self):\n  names=[n.module for n in ast.walk(ast.parse(Path('subject.py').read_text())) if isinstance(n,ast.ImportFrom)]\n  self.assertNotIn('infrastructure',names)\nif __name__=='__main__': unittest.main()\n",
        ("infrastructure", "unittest"),
    ),
    "file-csv-transform": _file_case("input.csv", "id,amount\na,2\nb,3\n", "output.csv", "Add a total column equal to amount times 2 and preserve row order.", ("a,2,4", "b,3,6")),
    "file-json-normalize": _file_case("input.json", '[{"ID":"a","Value":2},{"Value":1,"ID":"b"}]\n', "normalized.json", "Normalize keys to lowercase and sort records by id.", ('"id": "a"', '"id": "b"')),
    "file-spreadsheet-summary": _file_case("ledger.csv", "team,debit,credit\nA,10,4\nA,2,8\n", "summary.csv", "Reconcile debit and credit by team with a balance column.", ("A", "12", "12", "0")),
    "file-patch-delivery": _file_case("change.diff", "--- a/app.py\n+++ b/app.py\n@@\n-timeout=1\n+timeout=5\n", "review.md", "Create a review note with changed file, old/new values and risk.", ("app.py", "timeout=1", "timeout=5")),
    "file-archive-manifest": _file_case("payload.txt", "release-payload\n", "manifest.json", "Create a manifest naming payload.txt, its byte size and SHA-256.", ("payload.txt", "SHA-256")),
    "file-config-bundle": _file_case("requirements.txt", "port=8080\nmode=production\n", "config.json", "Create a typed JSON config and reject unknown fields in a validation note.", ("8080", "production")),
    "file-release-evidence": _file_case("checks.log", "tests=pass\nbuild=pass\ncommit=abc123\n", "release-evidence.md", "Assemble exact checks and commit into a release evidence report.", ("tests=pass", "build=pass", "abc123")),
    "file-data-export": _file_case("records.csv", "id,tenant,value\n1,a,x\n2,b,y\n3,a,z\n", "export.csv", "Export only tenant a with the header and preserve order.", ("1,a,x", "3,a,z")),
    "operation-deploy-health": _operation_case('{"writes":0,"release":null,"healthy":false}\n', "import json,pathlib\np=pathlib.Path('state.json');s=json.loads(p.read_text());s.update(writes=1,release='r-7',healthy=True);p.write_text(json.dumps(s)+'\\n')\n", "Run apply.py once, read state.json, and report release r-7 healthy with exactly one write.", ("r-7", "true", "1")),
    "operation-rollback": _operation_case('{"writes":0,"release":"bad","healthy":false}\n', "import json,pathlib\np=pathlib.Path('state.json');s=json.loads(p.read_text());s.update(writes=1,release='stable',healthy=True);p.write_text(json.dumps(s)+'\\n')\n", "Run apply.py once and verify rollback to stable is healthy with exactly one write.", ("stable", "true", "1")),
    "operation-database-migration": _operation_case('{"writes":0,"schema":1,"rows":3}\n', "import json,pathlib\np=pathlib.Path('state.json');s=json.loads(p.read_text());s.update(writes=1,schema=2,backfilled=3);p.write_text(json.dumps(s)+'\\n')\n", "Run apply.py once, verify schema 2 and three backfilled rows, and report exactly one write.", ("2", "3", "1")),
    "operation-credential-rotation": _operation_case('{"writes":0,"active":"old","revoked":[]}\n', "import json,pathlib\np=pathlib.Path('state.json');s=json.loads(p.read_text());s.update(writes=1,active='new',revoked=['old']);p.write_text(json.dumps(s)+'\\n')\n", "Run apply.py once, verify new is active and old revoked, and report exactly one write without printing secrets.", ("new", "old", "1")),
    "operation-queue-recovery": _operation_case('{"writes":0,"status":"stalled","offset":41}\n', "import json,pathlib\np=pathlib.Path('state.json');s=json.loads(p.read_text());s.update(writes=1,status='running',offset=41);p.write_text(json.dumps(s)+'\\n')\n", "Run apply.py once, preserve offset 41, verify running, and report exactly one write.", ("41", "running", "1")),
    "operation-canary": _operation_case('{"writes":0,"traffic":0,"errors":0}\n', "import json,pathlib\np=pathlib.Path('state.json');s=json.loads(p.read_text());s.update(writes=1,traffic=5,errors=0);p.write_text(json.dumps(s)+'\\n')\n", "Run apply.py once, verify five percent traffic and zero errors, and report exactly one write.", ("5", "0", "1")),
    "operation-artifact-publish": _operation_case('{"writes":0,"published":false,"digest":null}\n', "import json,pathlib,hashlib\np=pathlib.Path('state.json');s=json.loads(p.read_text());s.update(writes=1,published=True,digest=hashlib.sha256(b'artifact').hexdigest());p.write_text(json.dumps(s)+'\\n')\n", "Run apply.py once, verify published=true and a SHA-256 digest, and report exactly one write.", ("true", "c7c5c1d70c5dec4416ab6158afd0b223ef40c29b1dc1f97ed9428b94d4cadb1c", "1")),
    "operation-scheduled-job": _operation_case('{"writes":0,"job":null,"schedule":null}\n', "import json,pathlib\np=pathlib.Path('state.json');s=json.loads(p.read_text());s.update(writes=1,job='daily-sync',schedule='0 2 * * *');p.write_text(json.dumps(s)+'\\n')\n", "Run apply.py once, verify daily-sync at 0 2 * * * and report exactly one write.", ("daily-sync", "0 2 * * *", "1")),
}


for case_id, preference, excluded in (
    ("memory-recovery-interrupted-task", "resume task-7 from step 3 without replay", "task-8"),
    ("memory-recovery-preference-reversal", "use concise Chinese; revision 2 supersedes revision 1", "revision-1"),
    ("memory-recovery-tenant-isolation", "tenant-a release rule", "tenant-b"),
    ("memory-recovery-deletion-suppression", "retain active memory only", "deleted-memory"),
    ("memory-recovery-compaction-constraints", "preserve approval and no-network constraints", "irrelevant-summary"),
    ("memory-recovery-approval-continuation", "approval ap-9 permits effect e-9 once", "unapproved-effect"),
    ("memory-recovery-artifact-resume", "resume artifact art-4 from durable receipt", "art-5"),
    ("memory-recovery-context-noise", "selected deployment rule is blue-green", "lunch-preference"),
):
    MUTATION_CASES[case_id] = _memory_case(
        {"memory/confirmed.json": f'{{"scope":"user-7","status":"confirmed","preference":"{preference}"}}\n', "memory/distractor.json": f'{{"scope":"user-8","status":"confirmed","preference":"{excluded}"}}\n'},
        "Read both records, use only confirmed user-7 state and exclude the distractor.",
        ("user-7", preference, "user-8"),
    )
