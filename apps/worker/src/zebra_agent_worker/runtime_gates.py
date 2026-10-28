"""Actual Worker composition reuses its execution guard without running model/tools."""

import logging
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

from agent_core.domain.bundle_definition import parse_definition_snapshot
from agent_core.domain.runtime_gates import GateWork
from agent_storage.postgres.runtime_gate_worker import RuntimeGateWorkerStore
from zebra_agent_config import ZebraAgentSettings
from zebra_agent_config.bundle_settings import load_execution_catalog

from zebra_agent_worker.bundle_assembly import (
    require_snapshot_compatibility,
    require_task_compatibility,
)
from zebra_agent_worker.execution_finalization import RetryableWorkerSetupError
from zebra_agent_worker.runtime_preflight import check_runtime
from zebra_agent_worker.task_recovery import RecoveredTask, _model_invocation_policy


class RuntimeGateWorker:
    def __init__(self, settings: ZebraAgentSettings, namespace: str) -> None:
        self.settings = settings
        scope = load_execution_catalog(settings.runtime_bundle_config).scope
        if scope.namespace_id != namespace:
            raise ValueError("GATE_NAMESPACE_MISMATCH")
        self.store = RuntimeGateWorkerStore(
            settings.database_url, scope, settings.runtime.runtime_class
        )
        self._engine_available = False
        self.process = uuid4()
        self.pid = os.getpid()
        self.next_tick = 0.0
        self._executor = ThreadPoolExecutor(1, thread_name_prefix="runtime-gate")
        self._future: Future[None] | None = None
        self._closed = False
        self._lock = Lock()

    def evaluate(self, work: GateWork) -> tuple[bool, str]:
        if not self._engine_available:
            return False, "incompatible"
        if not work.source_complete:
            return False, "source_unproven"
        try:
            candidate = parse_definition_snapshot(work.candidate_snapshot)
            require_snapshot_compatibility(self.settings, candidate)
            for item in work.tasks:
                prepared = item["prepared"]
                snapshot = parse_definition_snapshot(prepared["definition_snapshot"])
                if snapshot.snapshot_schema_version not in {
                    "agent-definition-snapshot/2",
                    "agent-definition-snapshot/3",
                }:
                    return False, "source_unproven"
                task = SimpleNamespace(
                    definition_snapshot=snapshot,
                    coverage_admission=True if prepared["coverage"] else None,
                    model_invocation_policy=_model_invocation_policy(
                        item["user_policy"] or {}, prepared
                    ),
                )
                require_task_compatibility(self.settings, cast(RecoveredTask, task))
        except (ValueError, TypeError, KeyError, RetryableWorkerSetupError):
            return False, "incompatible"
        return True, "compatible"

    def _observe(self) -> None:
        # Reuse the actual bounded read-only engine preflight outside all DB locks.
        try:
            check_runtime(self.settings)
            self._engine_available = self.settings.runtime.runtime_class in {
                "trusted-local",
                "oci-rootless",
                "gvisor",
            }
        except Exception:
            self._engine_available = False
        try:
            self.store.tick(self.process, self.evaluate)
        except Exception:
            logging.getLogger(__name__).warning("runtime_gate_observation_unavailable")

    def tick(self) -> None:
        if os.getpid() != self.pid:
            return  # An inherited observer cannot attest or disrupt the child Worker.
        with self._lock:
            if (
                self._closed
                or time.monotonic() < self.next_tick
                or self._future is not None
                and not self._future.done()
            ):
                return
            self.next_tick = time.monotonic() + 2
            # One bounded observational job; never block execution, enqueue business work,
            # or allow a timed-out probe to accumulate behind another probe.
            self._future = self._executor.submit(self._observe)

    def close(self) -> None:
        if os.getpid() != self.pid:
            return  # Never revoke the parent process observation.
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=True)
        try:
            self.store.close(self.process)
        except Exception:
            logging.getLogger(__name__).warning("runtime_gate_observation_expiring")


def configure_runtime_gates(
    settings: ZebraAgentSettings, namespace: str | None
) -> RuntimeGateWorker | None:
    if settings.runtime_gate_config is None:
        return None
    if settings.storage_authority != "postgresql" or namespace is None:
        raise ValueError("Runtime gates require explicit cloud PostgreSQL composition")
    return RuntimeGateWorker(settings, namespace)
