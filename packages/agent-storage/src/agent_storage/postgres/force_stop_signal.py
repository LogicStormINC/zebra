"""Metadata-only stop lookup. Never lock an event stream to observe a stop."""

from typing import Any

STOP_REASON = "user_force_stop"
# ponytail: 32 immutable delegation edges per lookup; expanding deeper graphs
# requires derived stop markers or a raised bound, never an inferred cancellation.
# Admission uses its immutable historical binding: a later profile revision must
# never resurrect a stopped Task. Delegation edges retain their own frozen scope.
STOP_RECORDS = """
WITH RECURSIVE ancestors(task_id,depth) AS (
 SELECT s.task_id,0 FROM execution_segments s
 WHERE s.deployment_namespace=%(namespace)s AND s.session_id=%(sid)s
 UNION
 SELECT link.parent_task_id,a.depth+1
 FROM subagent_delegation_links link JOIN ancestors a ON link.child_task_id=a.task_id
 JOIN task_binding_snapshots b ON b.deployment_namespace=link.deployment_namespace
  AND b.task_id=link.parent_task_id AND b.binding_digest=link.parent_binding_digest
 JOIN task_binding_snapshots cb ON cb.deployment_namespace=link.deployment_namespace
  AND cb.task_id=link.child_task_id AND cb.binding_digest=link.child_binding_digest
 WHERE link.deployment_namespace=%(namespace)s AND a.depth<32
  AND cb.snapshot_json#>>'{host_capability,authority_issuer}'=
      b.snapshot_json#>>'{host_capability,authority_issuer}'
  AND cb.snapshot_json#>>'{host_capability,namespace_id}'=
      b.snapshot_json#>>'{host_capability,namespace_id}'
  AND cb.snapshot_json#>>'{host_capability,host_app_id}'=
      b.snapshot_json#>>'{host_capability,host_app_id}'
  AND cb.snapshot_json#>>'{host_capability,host_context,workspace_ref}'=
      b.snapshot_json#>>'{host_capability,host_context,workspace_ref}'
  AND cb.snapshot_json#>>'{host_capability,host_context,origin}'=
      b.snapshot_json#>>'{host_capability,host_context,origin}'
  AND jsonb_path_query_array(cb.snapshot_json,
      '$.host_capability.host_context.resource_refs[*] ?
       (@.type == "principal" || @.resource_type == "principal")')=
      jsonb_path_query_array(b.snapshot_json,
      '$.host_capability.host_context.resource_refs[*] ?
       (@.type == "principal" || @.resource_type == "principal")')
)
SELECT o.session_id FROM ancestors a JOIN execution_segments s ON s.task_id=a.task_id
 AND s.deployment_namespace=%(namespace)s JOIN agent_safety_overrides o
 ON o.session_id=s.session_id AND o.deployment_namespace=s.deployment_namespace
 WHERE o.kind='watchdog' AND o.reason='user_force_stop' AND NOT o.shadow
 AND (CASE WHEN o.reason='user_force_stop'
           THEN o.diagnostics::jsonb END)->>'task_id'=a.task_id::text
 AND EXISTS(SELECT 1 FROM task_binding_snapshots admitted
   WHERE admitted.deployment_namespace=%(namespace)s AND admitted.task_id=a.task_id
   AND admitted.binding_digest=(CASE WHEN o.reason='user_force_stop'
       THEN o.diagnostics::jsonb END)->>'binding_digest')
"""
STOP_ANCESTRY = STOP_RECORDS + " LIMIT 1"


def stop_requested(connection: Any, namespace: str, sid: Any) -> bool:
    row = connection.execute(STOP_ANCESTRY, {"namespace": namespace, "sid": sid}).fetchone()
    return row is not None
