"""Read bounded, principal-scoped Cloud usage evidence from committed Events."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from agent_core.domain.host_authority import HostContextEnvelope

from agent_storage.postgres.database import PostgresDatabase


class PostgresUsageEvidenceStore:
    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    @property
    def deployment_namespace(self) -> str:
        return self._database.deployment_namespace

    def read(
        self, context: HostContextEnvelope, *, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        principals = [
            ref.resource_id for ref in context.resource_refs if ref.resource_type == "principal"
        ]
        if len(principals) != 1:
            raise ValueError("usage read requires exactly one principal")
        principal_ref = json.dumps([{"resource_type": "principal", "resource_id": principals[0]}])
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                WITH latest_bindings AS (
                    SELECT DISTINCT ON (task_id) task_id, snapshot_json
                    FROM task_binding_snapshots
                    WHERE deployment_namespace = %s
                    ORDER BY task_id, binding_revision DESC
                ), authorized_tasks AS (
                    SELECT task_id FROM latest_bindings
                    WHERE snapshot_json #>> '{host_capability,host_context,host_app_id}' = %s
                      AND snapshot_json #>> '{host_capability,host_context,namespace_id}' = %s
                      AND snapshot_json #>> '{host_capability,host_context,workspace_ref}' = %s
                      AND snapshot_json #> '{host_capability,host_context,resource_refs}'
                          @> %s::jsonb
                )
                SELECT authorized_tasks.task_id, root.title, event.event_id,
                       event.event_type, event.created_at,
                       event.payload ->> 'input_tokens' AS input_tokens,
                       event.payload ->> 'output_tokens' AS output_tokens,
                       event.payload ->> 'total_tokens' AS total_tokens,
                       event.payload ->> 'reasoning_tokens' AS reasoning_tokens,
                       event.payload ->> 'prompt_cache_hit_tokens' AS cache_hit_tokens,
                       event.payload ->> 'prompt_cache_miss_tokens' AS cache_miss_tokens,
                       event.payload ->> 'resolved_model' AS resolved_model,
                       event.payload ->> 'model_name' AS model_name,
                       event.payload ->> 'tool_name' AS tool_name
                FROM authorized_tasks
                JOIN agent_tasks AS task
                  ON task.deployment_namespace = %s
                 AND task.task_id = authorized_tasks.task_id
                JOIN session_projections AS root
                  ON root.deployment_namespace = task.deployment_namespace
                 AND root.session_id = task.root_session_id
                JOIN execution_segments AS segment
                  ON segment.deployment_namespace = task.deployment_namespace
                 AND segment.task_id = task.task_id
                JOIN session_events AS event
                  ON event.deployment_namespace = segment.deployment_namespace
                 AND event.session_id = segment.session_id
                WHERE event.created_at >= %s AND event.created_at < %s
                  AND event.event_type IN (
                    'model_response_received', 'tool_execution_completed',
                    'tool_execution_failed', 'user_message_received'
                  )
                ORDER BY event.created_at, event.event_id
                LIMIT 100001
                """,
                (
                    self.deployment_namespace,
                    context.host_app_id,
                    context.namespace_id,
                    context.workspace_ref,
                    principal_ref,
                    self.deployment_namespace,
                    start,
                    end,
                ),
            ).fetchall()
        return [dict(row) for row in rows]
