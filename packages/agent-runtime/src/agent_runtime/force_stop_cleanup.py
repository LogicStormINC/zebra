"""Independent whole-Task stop recovery; exact engine I/O outside PG transactions."""

import logging

from agent_storage.postgres.force_stop_recovery import PostgresForceStopRecovery

from agent_runtime.adapters.oci_engine import PinnedOciEngine
from agent_runtime.command_runtime_cleanup import _remove_exact

_SAFE_CODES = frozenset(
    {
        "delegation_scope_conflict",
        "delegation_cycle",
        "stop_binding_changed",
        "stop_scope_changed",
        "stop_admission_unproven",
        "stop_target_budget_exceeded",
        "instance_identity_conflict",
        "creation_unsettled",
        "engine_unavailable",
    }
)


def recover_force_stops(
    dsn: str,
    *,
    deployment_namespace: str,
    engine: PinnedOciEngine | None,
    batch_size: int = 4,
    engine_timeout: float = 10,
) -> int:
    if type(batch_size) is not int or not 1 <= batch_size <= 16:
        raise ValueError("invalid force-stop recovery batch")
    if not 0 < engine_timeout <= 60:
        raise ValueError("invalid force-stop engine timeout")
    store = PostgresForceStopRecovery(dsn, deployment_namespace=deployment_namespace)
    settled = 0
    for sid in store.pending(
        batch_size, engine_identity=None if engine is None else engine.identity
    ):
        with store.claim(sid) as data:
            if data is None:
                continue
            execution = lease = sandbox = synchronized = True
            progress, code, operations = False, None, 0
            try:
                targets = store.targets(data)
                store.remember(data, targets)
                for target in targets:
                    try:
                        execution = store.revoke(target) and execution
                    except Exception:
                        lease = execution = sandbox = synchronized = False
                        code = code or "lease_revocation_pending"
                        continue
                    rows = store.instances(target)
                    for row in rows:
                        if operations >= 8:
                            sandbox = False
                            code = code or "cleanup_batch_pending"
                            break
                        operations += 1
                        if engine is None or row["engine_identity"] != engine.identity:
                            sandbox = False
                            code = code or "engine_unavailable"
                            continue
                        try:
                            exact = store.cleanup_target(target, row)
                        except ValueError:
                            sandbox = False
                            code = "instance_identity_conflict"
                            continue
                        container_id, error = _remove_exact(engine, "docker", exact, engine_timeout)
                        if error is not None or container_id is None:
                            sandbox = False
                            code = code or error or "engine_unavailable"
                        else:
                            store.removed(target, row, container_id)
                            progress = True
                    if store.instances(target):
                        sandbox = False
                    try:
                        store.synchronize(data, target)
                    except Exception:
                        synchronized = False
                        code = code or "canonical_sync_pending"
                # Child creation / segment rollover already in flight at admission
                # may commit before revocation. Never certify a partial old frontier.
                current = {str(t["session_id"]) for t in store.targets(data)}
                if current - set(data["target_sessions"]):
                    synchronized = False
                    code = "stop_frontier_advanced"
                if not execution:
                    code = code or "executor_exit_unconfirmed"
            except ValueError as error:
                execution = lease = sandbox = synchronized = False
                code = str(error) if str(error) in _SAFE_CODES else "invalid_stop_evidence"
            except Exception as error:
                execution = lease = sandbox = synchronized = False
                code = "stop_recovery_deferred"
                logging.warning("force_stop_recovery_deferred error_type=%s", type(error).__name__)
            store.finish(
                data,
                execution=execution,
                lease=lease,
                sandbox=sandbox,
                synchronized=synchronized,
                code=code,
                progress=progress,
            )
            settled += execution and lease and sandbox and synchronized and code is None
    return settled
