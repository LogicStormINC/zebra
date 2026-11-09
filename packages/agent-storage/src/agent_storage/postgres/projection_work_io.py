"""Existing remaining-budget SQL adapter for PostgreSQL projection maintenance."""

import time
from collections.abc import Mapping, Sequence
from typing import Any

from agent_core.ports.task_projection_checkpoints import CheckpointNotReady
from psycopg import ClientCursor, Connection, Cursor
from psycopg.errors import QueryCanceled

from agent_storage.projection_work_routing import routed_statements

REPAIR_HEADER_SIGNATURE = (
    "repair_task_projection_header(text,text,text,bigint,text,text,text,integer,text,text)"
)
_LEGACY_REPAIR_SOURCE = """SELECT %(namespace)s::text AS deployment_namespace,
 %(task_id)s::text AS task_id,%(event_id)s::text AS event_id,
 %(task_sequence)s::bigint AS task_sequence,%(event_type)s::text AS event_type,
 %(command_kind)s::text AS command_kind,%(run_id)s::text AS run_id,
 %(internal)s::integer AS internal,%(version)s::text AS selected_version"""
_LEGACY_REPAIR_BLOCK = (
    "BEGIN "
    + ";".join(routed_statements(_LEGACY_REPAIR_SOURCE, postgres=True, profiles=True))
    + ";PERFORM set_config('statement_timeout',%(finish_timeout)s,true);END"
)


class _WorkConnection:
    """Remaining SQL operation budget, shared by all statements and COMMIT."""

    def __init__(self, connection: Connection[dict[str, Any]], deadline: float) -> None:
        self.connection, self.deadline = connection, deadline

    def execute(
        self, statement: str, params: Sequence[Any] | Mapping[str, Any] | None = None
    ) -> Cursor[dict[str, Any]]:
        remaining = int((self.deadline - time.monotonic()) * 1000)
        if remaining <= 0:
            raise CheckpointNotReady("projection-work operation I/O deadline exceeded")
        try:
            self.connection.execute(
                "SELECT set_config('statement_timeout',%s,true),set_config('lock_timeout',%s,true)",
                (f"{remaining}ms", f"{min(50, remaining)}ms"),
            )
            return self.connection.execute(statement, params)
        except (QueryCanceled, TimeoutError) as exc:
            raise CheckpointNotReady("projection-work operation I/O deadline exceeded") from exc

    def repair_header(self, params: Mapping[str, Any], *, cached: bool) -> None:
        if cached:
            self.execute(
                """SELECT repair_task_projection_header(
                  %(namespace)s,%(task_id)s,%(event_id)s,%(task_sequence)s,
                  %(event_type)s,%(command_kind)s,%(run_id)s,%(internal)s,
                  %(version)s,%(finish_timeout)s)""",
                params,
            )
            return
        # ponytail: remove the anonymous block once the v122 rollout bridge retires.
        code = ClientCursor(self.connection).mogrify(_LEGACY_REPAIR_BLOCK, params)
        self.execute("DO %s", (code,))

    def commit(self) -> None:
        self.execute("COMMIT")
