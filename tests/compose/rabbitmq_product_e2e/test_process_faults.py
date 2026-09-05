"""Opt-in real subprocess/PG matrix. Transport, execution and OCI are injected.

Set ZEBRA_PROCESS_FAULT_POSTGRES_DSN to the exact owned stage3 loopback database.
Only a freshly generated process_fault_<uuid> schema is mutated or removed.
"""

import importlib.util
import json
import os
import queue
import subprocess
import sys
from io import StringIO
from pathlib import Path
from threading import Thread
from time import monotonic, sleep
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from agent_storage import apply_postgres_migrations
from psycopg import sql
from psycopg.conninfo import make_conninfo

from tests.agent_storage.test_command_wakeup import _command
from tests.agent_storage.test_postgres_command_wakeup import _seed, _store
from tests.agent_storage.test_postgres_command_wakeup_control import _intent
from tests.agent_storage.test_postgres_command_wakeup_handoff import _prepare
from tests.agent_storage.test_postgres_command_wakeup_receipts import _refresh

HERE = Path(__file__).parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location("fault_worker", HERE / "process_fault_worker.py")
assert spec and spec.loader
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class RedactedDsn(str):
    def __repr__(self):
        return "<isolated process fault DSN>"


@pytest.fixture
def fault_dsn():
    base = os.environ.get("ZEBRA_PROCESS_FAULT_POSTGRES_DSN")
    if not base:
        pytest.skip("explicit isolated process fault database not supplied")
    worker.validate_target(base)
    schema = "process_fault_" + uuid4().hex
    with psycopg.connect(base) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(base, options=f"-c search_path={schema}")
    try:
        apply_postgres_migrations(dsn)
        with psycopg.connect(dsn) as connection:
            connection.execute("CREATE TABLE process_effects (session_id uuid NOT NULL)")
        yield RedactedDsn(dsn)
    finally:
        # Exact locally generated identifier only; never use a caller-supplied schema.
        with psycopg.connect(base) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


class Child:
    def __init__(self, dsn, mode):
        worker.validate_target(dsn, child=True)
        self.expected_exit_code = 73 if mode == "crash_before_ack" else 0
        self.messages = queue.Queue()
        self.seen = []
        self.process = subprocess.Popen(
            [sys.executable, str(HERE / "process_fault_worker.py")],
            cwd=ROOT,
            env={
                "PATH": os.defpath,
                "PYTHONPATH": str(ROOT),
                "ZEBRA_PROCESS_FAULT_DSN": dsn,
                "ZEBRA_PROCESS_FAULT_MODE": mode,
            },
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )

        def read():
            assert self.process.stdout is not None
            for line in self.process.stdout:
                try:
                    self.messages.put(json.loads(line)["checkpoint"])
                except (ValueError, KeyError):
                    self.messages.put("invalid_child_checkpoint")

        self.reader = Thread(target=read, daemon=True)
        self.reader.start()

    def wait(self, checkpoint, timeout=10):
        deadline = monotonic() + timeout
        while checkpoint not in self.seen and monotonic() < deadline:
            try:
                self.seen.append(self.messages.get(timeout=0.05))
            except queue.Empty:
                pass
            assert "process_failed" not in self.seen, "child process failed (details withheld)"
        assert checkpoint in self.seen, f"missing safe checkpoint: {checkpoint}"

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)
            pytest.fail("child did not drain within bounded deadline")
        finally:
            self.reader.join(timeout=2)
            if self.process.stdout is not None:
                self.process.stdout.close()
        assert self.process.returncode == self.expected_exit_code, "unexpected child exit code"


@pytest.mark.parametrize("expected,actual", [(0, 0), (73, 73), (0, 1), (0, 73), (73, 0)])
def test_child_exit_contract_checks_after_cleanup(expected, actual):
    child = Child.__new__(Child)
    child.expected_exit_code = expected
    output = StringIO()
    joined = []
    child.process = SimpleNamespace(
        poll=lambda: actual,
        wait=lambda **_kwargs: actual,
        returncode=actual,
        stdout=output,
    )
    child.reader = SimpleNamespace(join=lambda **_kwargs: joined.append(True))
    if expected == actual:
        child.__exit__(None, None, None)
    else:
        with pytest.raises(AssertionError, match="unexpected child exit code"):
            child.__exit__(None, None, None)
    assert joined == [True] and output.closed


def scalar(dsn, statement, args=()):
    with psycopg.connect(dsn) as connection:
        return connection.execute(statement, args).fetchone()[0]


def wait_db(dsn, statement, args=(), timeout=8):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if scalar(dsn, statement, args):
            return
        sleep(0.02)
    pytest.fail("isolated database checkpoint timed out")


def prepare(dsn):
    event = _prepare(dsn)
    _refresh(dsn, event.session_id)
    return event


def test_crash_before_injected_ack_then_process_recovery(fault_dsn):
    dsn = fault_dsn
    event = prepare(dsn)
    with Child(dsn, "crash_before_ack") as child:
        child.wait("handoff_committed_before_ack")
        assert child.process.wait(timeout=3) == 73
    assert scalar(dsn, "SELECT count(*) FROM process_effects") == 0
    assert scalar(dsn, "SELECT started_event_id IS NULL FROM command_handoff_receipts")
    # Real DB lease time elapses. Accelerate only the isolated recovery scheduling deadline.
    wait_db(dsn, "SELECT clock_timestamp()>expires_at FROM worker_leases")
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE session_command_pending SET recovery_due_at=clock_timestamp()")
    with Child(dsn, "broker") as child:
        child.wait("handled")
    assert scalar(dsn, "SELECT count(*) FROM process_effects") == 1
    assert scalar(dsn, "SELECT wake_generation FROM command_handoff_receipts") == 1
    assert scalar(dsn, "SELECT count(*) FROM command_recovery_attempts") == 1
    assert scalar(dsn, "SELECT handled_event_id IS NOT NULL FROM command_handoff_receipts")
    assert scalar(dsn, "SELECT session_id FROM process_effects") == event.session_id


def test_occupied_process_execution_does_not_block_canonical_control(fault_dsn):
    dsn = fault_dsn
    event = prepare(dsn)
    with Child(dsn, "occupied") as child:
        child.wait("started")
        _intent(dsn, event.session_id, "cancel")
        child.wait("revoked_while_occupied", timeout=5)
        wait_db(dsn, "SELECT count(*)=1 FROM command_control_receipts WHERE outcome='cancelled'")
    assert scalar(dsn, "SELECT count(*) FROM process_effects") == 0
    assert scalar(dsn, "SELECT handled_event_id IS NULL FROM command_handoff_receipts")


def test_flag_rollback_process_keeps_receipt_no_duplicate_effect(fault_dsn):
    dsn = fault_dsn
    prepare(dsn)
    with Child(dsn, "broker") as child:
        child.wait("handled")
    original = scalar(dsn, "SELECT handled_event_id FROM command_handoff_receipts")
    with psycopg.connect(dsn) as connection:
        # A stale derived candidate must still respect the authoritative handled receipt.
        connection.execute("UPDATE session_command_pending SET status='pending'")
    # Real flag rollback: restart the process with all Rabbit flags disabled.
    with Child(dsn, "fallback") as child:
        child.wait("drained")  # Six real fallback cycles, not a timing-only sleep assertion.
        assert child.process.wait(timeout=3) == 0
    assert child.process.returncode == 0
    assert scalar(dsn, "SELECT count(*) FROM process_effects") == 1
    assert scalar(dsn, "SELECT handled_event_id FROM command_handoff_receipts") == original
    assert scalar(dsn, "SELECT fencing_token FROM worker_leases") == 1


def test_poison_first_does_not_starve_next_process_candidate(fault_dsn):
    dsn = fault_dsn
    poison = prepare(dsn)
    healthy = _seed(dsn)
    _store(dsn).append(_command(healthy.session_id))
    _refresh(dsn, healthy.session_id)
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE broker_outbox SET envelope_digest=%s WHERE operation_id=%s",
            ("0" * 64, poison.payload["command_id"]),
        )
    with Child(dsn, "poison") as child:
        child.wait("handled")
        wait_db(dsn, "SELECT count(*)>0 FROM command_delivery_rejections WHERE status='published'")
    assert scalar(dsn, "SELECT count(*) FROM process_effects") == 1
    assert scalar(dsn, "SELECT session_id FROM process_effects") == healthy.session_id
    assert (
        scalar(
            dsn,
            "SELECT count(*) FROM command_handoff_receipts WHERE session_id=%s",
            (poison.session_id,),
        )
        == 0
    )


@pytest.mark.parametrize("change", ["host", "database", "query", "password", "schema"])
def test_fault_target_guard_is_non_networked(change):
    base = f"postgresql://e2e:{'a' * 48}@127.0.0.1:28432/zebra_stage3_e2e"
    assert worker.validate_target(base) is None
    invalid = {
        "host": base.replace("127.0.0.1", "postgres"),
        "database": base.replace("zebra_stage3_e2e", "zebra_e2e"),
        "query": base + "?hostaddr=203.0.113.1",
        "password": base.replace("a" * 48, "bad"),
        "schema": make_conninfo(base, options="-c search_path=public"),
    }[change]
    with pytest.raises(ValueError, match="explicit isolated"):
        worker.validate_target(invalid, child=change == "schema")


def test_child_imports_and_rejects_unsafe_target_without_network():
    result = subprocess.run(
        [sys.executable, str(HERE / "process_fault_worker.py")],
        cwd=ROOT,
        env={
            "PATH": os.defpath,
            "PYTHONPATH": str(ROOT),
            "ZEBRA_PROCESS_FAULT_DSN": "postgresql://fake:sentinel@foreign/db",
            "ZEBRA_PROCESS_FAULT_MODE": "fallback",
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout) == {"checkpoint": "process_failed"}
    assert "sentinel" not in result.stdout + result.stderr
