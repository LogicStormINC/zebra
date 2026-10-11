"""Post-lock native authority facts shared by all coverage write operations."""

from typing import Any, cast

from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.leases import LeaseFence

from agent_storage.postgres.coverage_authority import lock_coverage_lease, validate_coverage_lease


def read_write_authority(
    connection: Any, deployment: str, binding: CoverageRunBinding, fence: LeaseFence,
) -> dict[str, Any]:
    lease = lock_coverage_lease(connection, deployment, binding.session_id)
    # Deliberately separate statements: a lease wait must not leave binding/STOP
    # checks on the pre-wait READ COMMITTED snapshot. No authority TTL is used.
    row = connection.execute(
        """SELECT clock_timestamp() AS now,
             (SELECT jsonb_build_object('snapshot_json',b.snapshot_json,
                 'binding_digest',b.binding_digest,'namespace_id',s.namespace_id)
              FROM execution_segments segment JOIN session_projections s
                ON s.deployment_namespace=segment.deployment_namespace
                  AND s.session_id=segment.session_id
              JOIN LATERAL (SELECT snapshot_json,binding_digest FROM task_binding_snapshots
                WHERE deployment_namespace=segment.deployment_namespace
                  AND task_id=segment.task_id ORDER BY binding_revision DESC LIMIT 1) b ON TRUE
              WHERE segment.deployment_namespace=%s AND segment.session_id=%s
                AND segment.task_id=%s) AS authority,
             (SELECT coalesce(jsonb_agg(to_jsonb(e)),'[]'::jsonb) FROM (
                SELECT payload FROM session_events WHERE deployment_namespace=%s
                  AND payload->>'namespace'=%s AND payload->>'run_id'=%s
                  AND event_type='coverage_manifest_committed' LIMIT 2) e) AS manifests,
             EXISTS(SELECT 1 FROM session_events WHERE deployment_namespace=%s AND session_id=%s
               AND (event_type IN ('session_cancelled','session_failed','session_completed')
                 OR (event_type='session_command_accepted'
                     AND payload->>'kind' IN ('stop','cancel')))) AS stopped""",
        (deployment, binding.session_id, binding.task_id,
         deployment, binding.namespace, binding.run_id, deployment, binding.session_id),
    ).fetchone()
    validate_coverage_lease(lease, fence, row["now"])
    if len(row["manifests"]) > 1:
        raise ValueError("coverage run has conflicting source manifests")
    return cast(dict[str, Any], row)
