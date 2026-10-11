"""Read-only cutover checks and bounded canonical scope discovery for maintenance."""

import os
from collections.abc import Callable
from functools import partial
from threading import Lock
from time import monotonic
from typing import Any
from uuid import uuid4

from agent_storage.postgres.command_wakeup_discovery import PendingCursor
from agent_storage.postgres.command_wakeup_pickup import (
    PickupLane,
    PickupScopeMode,
    discover_command_pickups,
    resolve_command_pickup,
)
from agent_storage.postgres.command_wakeup_recovery import recover_command_batch
from agent_storage.postgres.command_wakeup_recovery_proof import CoverageRecoveryCheck
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.migrations import MIGRATIONS
from agent_storage.postgres.worker_capability import (
    PostgresWorkerCapabilities,
    WorkerCapabilityExpiredError,
    WorkerCapabilityLease,
    WorkerCapabilityLostError,
)
from agent_storage.worker_capability_configuration import (
    continuation_configuration_digest,
    worker_capability_configuration_digest,
)
from zebra_agent_config import ZebraAgentSettings


def command_cutover_state(dsn: str, namespace: str, *, require_ready: bool = False) -> bool:
    with PostgresDatabase(dsn, deployment_namespace=namespace).connect() as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        exists = connection.execute(
            "SELECT to_regclass('command_wakeup_rollouts') AS name"
        ).fetchone()
        if exists is None or exists["name"] is None:
            if require_ready:
                raise ValueError("command delivery requires operator migration and cutover")
            return False
        row = connection.execute(
            """SELECT admission_enabled,
            COALESCE(to_jsonb(rollout)->>'backfill_state','not_started') AS backfill_state
            FROM command_wakeup_rollouts rollout
            WHERE deployment_namespace=%s""",
            (namespace,),
        ).fetchone()
        migrated = row is not None and (
            row["admission_enabled"] or row["backfill_state"] != "not_started"
        )
        if not migrated:
            migrated = (
                connection.execute(
                    """SELECT 1 FROM session_command_pending
                WHERE deployment_namespace=%s LIMIT 1""",
                    (namespace,),
                ).fetchone()
                is not None
            )
        if migrated or require_ready:
            applied = {
                r["version"]: r
                for r in connection.execute(
                    "SELECT version,name,checksum FROM zebra_schema_migrations"
                ).fetchall()
            }
            if any(
                m.version not in applied
                or (applied[m.version]["name"], applied[m.version]["checksum"])
                != (m.name, m.checksum)
                for m in MIGRATIONS
            ):
                raise ValueError("command delivery requires the complete verified schema")
        if require_ready and not migrated:
            raise ValueError("command delivery requires explicit operator cutover")
        return bool(migrated)


class CommandRecoverySweep:
    def __init__(
        self,
        dsn: str,
        namespace: str,
        batch_size: int,
        *,
        scope_mode: PickupScopeMode = "all",
        coverage_check: CoverageRecoveryCheck | None = None,
    ) -> None:
        self._dsn, self._namespace, self._batch = dsn, namespace, batch_size
        self._coverage_check = coverage_check
        if scope_mode not in ("all", "fallback"):
            raise ValueError("invalid recovery scope mode")
        self._scope_mode = scope_mode
        self._cursors: dict[PickupLane, PendingCursor | None] = {"execution": None, "control": None}

    def tick(self) -> None:
        scopes = set()
        for lane in ("execution", "control"):
            rows = discover_command_pickups(
                self._dsn,
                deployment_namespace=self._namespace,
                lane=lane,
                batch_size=self._batch,
                after=self._cursors[lane],
                scope_mode=self._scope_mode,
            )
            if not rows:
                self._cursors[lane] = None
            for row in rows:
                try:
                    resolved = resolve_command_pickup(
                        self._dsn,
                        deployment_namespace=self._namespace,
                        accepted_event_id=row.accepted_event_id,
                    )
                except ValueError:
                    # Invalid hints remain quarantine responsibility; advance this bounded page.
                    self._cursors[lane] = row.cursor
                    continue
                if resolved.scope not in scopes:
                    recover_command_batch(
                        self._dsn,
                        deployment_namespace=self._namespace,
                        scope=resolved.scope,
                        batch_size=self._batch,
                        coverage_check=self._coverage_check,
                    )
                    scopes.add(resolved.scope)
                self._cursors[lane] = row.cursor


def strict_worker_configuration_digest(
    dsn: str,
    namespace: str,
    settings: ZebraAgentSettings,
    execute: Callable[..., object],
    coverage_check: CoverageRecoveryCheck | None,
) -> str | None:
    """Inspect the actual bound composition, not a caller's ready declaration.

    Capability is executable wiring, NOT per-Task authority or provider health.
    Those proofs still run on every strict execution/recovery. Broker-only and
    arbitrary injected callbacks deliberately cannot publish this scan contract.
    """
    from agent_integrations.coverage_model_policy import REVIEWER_PROFILE
    from agent_storage import (
        PostgresCloudArtifactPayloadStore,
        PostgresEventStore,
        PostgresGovernedMemoryStore,
        PostgresLeaseStore,
        PostgresProjectionStore,
        S3ArtifactObjectStore,
    )

    from zebra_agent_worker.coverage_composition import CloudCoverageRuntime
    from zebra_agent_worker.coverage_recovery_preparation import NativeCoverageRecoveryCheck
    from zebra_agent_worker.execution import SessionExecutionService
    from zebra_agent_worker.execution_entrypoints import SessionExecutionEntrypoints

    service = getattr(execute, "__self__", None)
    if (
        type(service) is not SessionExecutionService
        or getattr(execute, "__func__", None)
        is not SessionExecutionEntrypoints.execute_claimed_session
        or service._settings is not settings
        or not callable(getattr(service, "_task_binding_loader", None))
        or not callable(getattr(service, "_cloud_artifact_factory", None))
        or settings.deployment != "cloud"
        or settings.storage_authority != "postgresql"
        or not settings.command_delivery.scan_fallback_enabled
        or settings.model.provider != "deepseek"
        or settings.model.base_url != "https://api.deepseek.com"
        or settings.model.model != "deepseek-v4-pro"
        or settings.model.reviewer_profile != REVIEWER_PROFILE
        or not os.environ.get(settings.model.api_key_env, "").strip()
    ):
        return None
    runtime = service._coverage_runtime
    if (
        type(runtime) is not CloudCoverageRuntime
        or runtime.dsn != dsn
        or runtime.deployment_namespace != namespace
        or type(runtime.metadata) is not PostgresCloudArtifactPayloadStore
        or type(runtime.objects) is not S3ArtifactObjectStore
        or not (
            (
                type(coverage_check) is NativeCoverageRecoveryCheck
                and coverage_check.runtime is runtime
                and coverage_check.service is service
                and callable(getattr(runtime.objects, "_deadline_client_factory", None))
            )
            or (
                type(coverage_check) is partial
                and coverage_check.func == runtime.recovery_check
                and coverage_check.args == (service,)
                and not coverage_check.keywords
            )
        )
    ):
        return None
    native = (
        (runtime.metadata, PostgresCloudArtifactPayloadStore),
        (service._event_store, PostgresEventStore),
        (service._projection_store, PostgresProjectionStore),
        (getattr(service, "_cloud_memory_store", None), PostgresGovernedMemoryStore),
        (service._claim_service._lease_store, PostgresLeaseStore),
    )
    if service._deployment_namespace != namespace or any(
        type(store) is not expected
        or store._database._dsn != dsn
        or store._database.deployment_namespace != namespace
        for store, expected in native
    ):
        return None
    try:
        return worker_capability_configuration_digest(
            settings,
            namespace=namespace,
            bucket=runtime.objects._bucket,
            key_prefix=runtime.objects._key_prefix,
            object_endpoint=getattr(
                getattr(runtime.objects._client, "meta", None), "endpoint_url", None
            ),
        )
    except ValueError:
        return None


def strict_continuation_configuration_digest(
    dsn: str, namespace: str, settings: ZebraAgentSettings,
    execute: Callable[..., object], coverage_check: CoverageRecoveryCheck | None,
) -> str | None:
    """Qualification only: do not replace the deployed v3 fleet contract here."""
    from agent_integrations.coverage_model_derivation import derive_semantic_observation

    from zebra_agent_worker import coverage_dispatch
    from zebra_agent_worker.coverage_recovery_preparation import NativeCoverageRecoveryCheck

    base = strict_worker_configuration_digest(dsn, namespace, settings, execute, coverage_check)
    if (
        base is None or type(coverage_check) is not NativeCoverageRecoveryCheck
        or getattr(coverage_dispatch, "derive_semantic_observation", None)
        is not derive_semantic_observation
        or getattr(coverage_check.prepare_continuation, "__func__", None)
        is not NativeCoverageRecoveryCheck.prepare_continuation
    ):
        return None
    return continuation_configuration_digest(base)


class CommandWorkerCapability:
    """Renew only after successful native execution polling AND recovery work."""

    def __init__(
        self,
        dsn: str,
        namespace: str,
        settings: ZebraAgentSettings,
        execute: Callable[..., object],
        coverage_check: CoverageRecoveryCheck | None,
    ) -> None:
        self._dsn, self._namespace = dsn, namespace
        self._settings, self._execute, self._check = settings, execute, coverage_check
        self._store = PostgresWorkerCapabilities(dsn, deployment_namespace=namespace)
        self._process = uuid4()
        self._lease: WorkerCapabilityLease | None = None
        self._generation = 0
        self._execution_generation = 0
        self._lock = Lock()
        self._closed = False
        self._consumer: Any = None

    def lease_for(self, consumer: Any) -> WorkerCapabilityLease | None:
        """Only the actual consumer that performed qualified progress gets the token."""
        with self._lock:
            if self._closed or self._consumer is not consumer or consumer._closed:
                return None
            return self._lease

    def consumer_tick(
        self,
        consumer: Any,
        recovery_generation: int,
        work_completed_at: float,
    ) -> None:
        with self._lock:
            if not self._closed and 0 <= monotonic() - work_completed_at <= 5:
                self._tick_locked(consumer, recovery_generation)

    def _tick_locked(self, consumer: Any, recovery_generation: int) -> None:
        from agent_runtime.command_wakeup_consumer import CommandWakeupConsumer

        if recovery_generation <= self._generation:
            return
        execution_generation = getattr(consumer, "_execution_discovery_generation", 0)
        if execution_generation <= self._execution_generation:
            return
        self._execution_generation = execution_generation
        self._generation = recovery_generation
        digest = strict_worker_configuration_digest(
            self._dsn, self._namespace, self._settings, self._execute, self._check
        )
        if (
            digest is None
            or type(consumer) is not CommandWakeupConsumer
            or consumer._dsn != self._dsn
            or consumer._namespace != self._namespace
            or consumer._coverage_check is not self._check
            or consumer._closed
        ):
            self._closed = True
            self._revoke_locked()
            return
        try:
            qualification = strict_continuation_configuration_digest(
                self._dsn, self._namespace, self._settings, self._execute, self._check
            )
            self._lease = (
                self._store.register(
                    self._process, configuration_digest=digest, continuation_digest=qualification,
                )
                if self._lease is None
                else self._store.heartbeat(
                    self._lease, configuration_digest=digest, continuation_digest=qualification,
                )
            )
        except WorkerCapabilityExpiredError:
            replacement = uuid4()
            try:
                self._lease = self._store.register(
                    replacement,
                    configuration_digest=digest,
                    expired_lease=self._lease,
                    continuation_digest=qualification,
                )
            except WorkerCapabilityLostError:
                self._closed = True
                self._revoke_locked()
                raise
            self._process = replacement
        except WorkerCapabilityLostError:
            self._closed = True
            self._revoke_locked()
            raise
        self._consumer = consumer

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._revoke_locked()

    def _revoke_locked(self) -> None:
        if self._lease is not None:
            self._store.revoke(self._lease)
