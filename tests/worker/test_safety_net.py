"""Worker safety net: bounded structural retries, dead-letter escalation, shadow mode.

The 2026-10-29 ERP incident: a recorder sequence mismatch failed every worker
recovery attempt; the loop re-picked the session forever (11h "running"). These
tests pin the contract that stops that loop — structural failures count,
transient ones never do, the cap escalates to a control-plane terminal,
shadow mode observes without terminalizing, and terminal overrides gate
execution. Storage outages fail open and never break the loop itself.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from zebra_agent_worker.safety_net import SafetyNetConfig, WorkerSafetyNet

NAMESPACE = "erpnext-full"


class FakeStore:
    """Mirrors PostgresSafetyOverrideStore semantics for the worker logic."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def record_failure(self, *, namespace, session_id, reason, structural, max_attempts, shadow):
        row = self.rows.get(session_id)
        attempts = (row["attempts"] + 1) if row and row["kind"] == "failure_count" else 1
        terminal = structural and attempts >= max_attempts
        self.rows[session_id] = {
            "kind": "dead_letter" if terminal else "failure_count",
            "attempts": attempts,
            "shadow": shadow,
        }
        return _Record(
            session_id=session_id,
            kind=self.rows[session_id]["kind"],
            reason=reason,
            attempts=attempts,
            shadow=shadow,
        )

    def terminal(self, *, namespace, session_id):
        row = self.rows.get(session_id)
        return row if row and row["kind"] == "dead_letter" and not row["shadow"] else None


class _Record:
    def __init__(self, *, session_id, kind, reason, attempts, shadow):
        self.session_id, self.kind, self.reason = session_id, kind, reason
        self.attempts, self.shadow = attempts, shadow

    @property
    def is_terminal(self):
        return self.kind == "dead_letter" and not self.shadow


def build(store: FakeStore, **config: Any) -> WorkerSafetyNet:
    @contextmanager
    def store_context():
        yield store

    return WorkerSafetyNet(
        namespace=NAMESPACE,
        store_context=store_context,
        config=SafetyNetConfig(**config),
    )


MISMATCH = ValueError("execution event sequence does not match recorder")


def test_structural_failures_escalate_to_dead_letter() -> None:
    store = FakeStore()
    net = build(store, enabled=True, shadow=False, dead_letter_max_attempts=3)
    session = str(uuid4())
    for _ in range(2):
        net.note_recovery_failure(session, "continuation_recovery", MISMATCH)
    assert store.rows[session]["kind"] == "failure_count"
    net.note_recovery_failure(session, "continuation_recovery", MISMATCH)
    assert store.rows[session]["kind"] == "dead_letter"
    assert net.should_skip(session) is True


def test_transient_failures_never_count() -> None:
    store = FakeStore()
    net = build(store, enabled=True, shadow=False, dead_letter_max_attempts=2)
    session = str(uuid4())
    for _ in range(10):
        net.note_recovery_failure(session, "session_scan", psycopg.OperationalError("db blip"))
    assert session not in store.rows, "transient failures must never be counted"
    assert net.should_skip(session) is False


def test_command_reason_text_counts_as_structural() -> None:
    store = FakeStore()
    net = build(store, enabled=True, shadow=False, dead_letter_max_attempts=1)
    session = str(uuid4())
    net.note_recovery_failure(
        session, "command:resume", None, reason="execution event sequence does not match recorder"
    )
    assert store.rows[session]["kind"] == "dead_letter"


def test_shadow_mode_records_but_never_gates() -> None:
    store = FakeStore()
    net = build(store, enabled=True, shadow=True, dead_letter_max_attempts=1)
    session = str(uuid4())
    net.note_recovery_failure(session, "continuation_recovery", MISMATCH)
    assert store.rows[session]["kind"] == "dead_letter"
    assert store.rows[session]["shadow"] is True
    assert net.should_skip(session) is False, "shadow dead-letters never gate execution"


def test_disabled_net_is_inert() -> None:
    store = FakeStore()
    net = build(store, enabled=False)
    session = str(uuid4())
    net.note_recovery_failure(session, "stage", MISMATCH)
    assert store.rows == {}
    assert net.should_skip(session) is False


def test_storage_outage_fails_open_and_never_raises() -> None:
    class Broken:
        def __enter__(self):
            raise psycopg.OperationalError("safety net storage down")

        def __exit__(self, *args):
            return False

    net = WorkerSafetyNet(
        namespace=NAMESPACE,
        store_context=Broken,
        config=SafetyNetConfig(enabled=True, shadow=False),
    )
    session = str(uuid4())
    net.note_recovery_failure(session, "stage", MISMATCH)  # must not raise
    assert net.should_skip(session) is False


def test_config_env_parsing_defaults_and_clamps() -> None:
    config = SafetyNetConfig.from_env(
        {
            "ZEBRA_WORKER_SAFETY_NET_ENABLED": "true",
            "ZEBRA_WORKER_SAFETY_NET_SHADOW": "false",
            "ZEBRA_WORKER_SAFETY_NET_DEAD_LETTER_MAX_ATTEMPTS": "7",
        }.get
    )
    assert (config.enabled, config.shadow, config.dead_letter_max_attempts) == (True, False, 7)
    assert SafetyNetConfig.from_env({}.get).shadow is True, "shadow ships as default posture"
    clamped = SafetyNetConfig.from_env(
        {"ZEBRA_WORKER_SAFETY_NET_DEAD_LETTER_MAX_ATTEMPTS": "9999"}.get
    )
    assert clamped.dead_letter_max_attempts == 5, "out-of-range caps clamp to the safe default"


def test_store_requires_connection_or_context() -> None:
    with pytest.raises(ValueError):
        WorkerSafetyNet(namespace=NAMESPACE)
