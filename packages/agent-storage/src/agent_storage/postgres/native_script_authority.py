"""Short current-Host fence sharing the existing leased event transaction."""

from collections.abc import Callable
from time import monotonic
from typing import TypeVar

import psycopg
from agent_core.application.native_script import (
    NativeScriptReceiptUncertain,
    NativeScriptUnavailable,
)
from agent_core.domain.native_script_receipt import NativeScriptEvent
from agent_core.domain.task_bindings import TaskBindingSnapshot, task_bound_host_thread
from agent_core.ports.event_store import EventStorePort
from agent_core.ports.native_script import NativeScriptJournalPort

from agent_storage.postgres.events import PostgresEventStore
from agent_storage.postgres.task_io import task_io_deadline
from agent_storage.postgres.work_unit import postgres_transaction_work_unit

T = TypeVar("T")


class NativeScriptAuthority:
    def __init__(self, events: EventStorePort, binding: TaskBindingSnapshot) -> None:
        if not isinstance(events, PostgresEventStore):
            raise NativeScriptUnavailable("NATIVE_SCRIPT_REQUIRES_POSTGRES")
        task_bound_host_thread(binding, task_id=binding.task_id)
        self._database, self._binding = events._database, binding

    def checked(self, action: Callable[[], T]) -> T:
        """No script/network work in this transaction; only a bounded local event append."""
        host = self._binding.host_capability
        context = host.host_context
        assert context is not None
        if host.grant_expires_at is None or context.expires_at is None:
            raise NativeScriptUnavailable("NATIVE_SCRIPT_HOST_AUTHORITY_UNAVAILABLE")
        with task_io_deadline(monotonic() + 2):
            with self._database.connect_task_io() as connection:
                row = connection.execute(
                    """SELECT issuer, allowed_origins, policy_version, active,
                         clock_timestamp() AS observed_at
                       FROM host_authority_registries
                       WHERE deployment_namespace=%s AND host_app_id=%s AND namespace_id=%s
                       FOR SHARE""",
                    (self._database.deployment_namespace, host.host_app_id, host.namespace_id),
                ).fetchone()
                if (
                    row is None
                    or not row["active"]
                    or row["issuer"] != host.authority_issuer
                    or row["policy_version"] != context.policy_version
                    or context.origin not in row["allowed_origins"]
                    or min(host.grant_expires_at, context.expires_at) <= row["observed_at"]
                ):
                    raise NativeScriptUnavailable("NATIVE_SCRIPT_HOST_AUTHORITY_UNAVAILABLE")
                with postgres_transaction_work_unit(self._database, connection):
                    return action()

    def commit(self, action: Callable[[], T]) -> T:
        try:
            return self.checked(action)
        except (TimeoutError, psycopg.Error) as exc:
            # Recorder caches may have advanced before the outer transaction exit.
            # Stop this attempt; recovery must rebuild from independently read facts.
            raise NativeScriptReceiptUncertain("NATIVE_SCRIPT_RECEIPT_UNCERTAIN") from exc

    def check(self) -> None:
        self.checked(lambda: None)


class PostgresScriptJournal:
    def __init__(self, journal: NativeScriptJournalPort) -> None:
        self._journal = journal

    def read(self, invocation_id: str) -> tuple[NativeScriptEvent, ...]:
        with task_io_deadline(monotonic() + 2):
            return self._journal.read(invocation_id)

    def append(self, event: NativeScriptEvent) -> None:
        try:
            self._journal.append(event)
        except (TimeoutError, psycopg.Error) as exc:
            raise NativeScriptReceiptUncertain("NATIVE_SCRIPT_RECEIPT_UNCERTAIN") from exc
