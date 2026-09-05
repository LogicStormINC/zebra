"""Explicit bounded post-commit cleanup tick; no process wiring or session sweeps."""

import json
import math
from datetime import timedelta

from agent_core.ports.runtime import RuntimeCapabilityError
from agent_storage.postgres.command_runtime_cleanup import (
    CleanupTarget,
    claim_runtime_cleanup,
    settle_runtime_cleanup,
)

from agent_runtime.adapters.oci_engine import PinnedOciEngine
from agent_runtime.adapters.oci_instances import verify_instance_metadata


def cleanup_runtime_batch(
    dsn: str,
    *,
    deployment_namespace: str,
    owner: str,
    engine: PinnedOciEngine,
    engine_command: str = "docker",
    batch_size: int = 8,
    engine_timeout: float = 10,
    lease_ttl: timedelta = timedelta(seconds=90),
) -> int:
    """One immediately processed instance per claim, bounded by batch_size (1..32).

    Synchronous by design: composition may run this on its dedicated cleanup
    executor. Every engine command has a timeout and runs outside PG transactions.
    Return successful settlements, not a promise that every obligation is done.
    """
    if (
        type(batch_size) is not int
        or not 1 <= batch_size <= 32
        or type(engine_timeout) not in (int, float)
        or not math.isfinite(engine_timeout)
        or not 0 < engine_timeout <= 60
        or not isinstance(lease_ttl, timedelta)
        # Pinned Docker also performs a bounded 10s daemon identity probe per command.
        or not timedelta(seconds=3 * (engine_timeout + 10) + 5) < lease_ttl <= timedelta(minutes=5)
    ):
        raise ValueError("invalid bounded runtime cleanup settings")
    settled = 0
    for _ in range(batch_size):
        claim = claim_runtime_cleanup(
            dsn,
            deployment_namespace=deployment_namespace,
            owner=owner,
            engine_identity=engine.identity,
            ttl=lease_ttl,
        )
        if claim is None:
            break
        if not claim.leased:
            continue
        container_id, code = None, None
        if claim.target is not None:
            container_id, code = _remove_exact(engine, engine_command, claim.target, engine_timeout)
        settled += settle_runtime_cleanup(
            dsn, claim, removed_container_id=container_id, error_code=code
        )
    return settled


def _remove_exact(
    engine: PinnedOciEngine, command: str, target: CleanupTarget, timeout: float
) -> tuple[str | None, str | None]:
    def invoke(*args: str) -> str:
        result = engine(
            (command, *args), timeout=timeout, capture_output=True, text=True, check=False
        )
        if result.returncode:
            raise RuntimeError("engine operation failed")
        return result.stdout

    try:
        selector = (
            f"id={target.container_id}"
            if target.container_id is not None
            else f"name=^{target.container_name}$"
        )
        listed = invoke("ps", "--all", "--no-trunc", "--quiet", "--filter", selector)
        ids = listed.splitlines()
        if not ids:
            if target.container_id is None:
                return None, "creation_unsettled"
            return target.container_id, None
        if len(ids) != 1 or (target.container_id is not None and ids[0] != target.container_id):
            return None, "instance_identity_conflict"
        container_id = ids[0]
        if len(container_id) != 64 or any(c not in "0123456789abcdef" for c in container_id):
            return None, "instance_identity_conflict"
        metadata = json.loads(invoke("inspect", "--format", "{{json .}}", container_id))
        verify_instance_metadata(metadata, container_id, target.container_name, dict(target.labels))
        invoke("rm", "--force", "--volumes", container_id)
        return container_id, None
    except RuntimeCapabilityError:
        return None, "instance_identity_conflict"
    except Exception:
        # No raw exception, engine output, credential or container environment is retained.
        return None, "engine_unavailable"
