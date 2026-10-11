"""Additive v68: scalar durable derived-work routing, no execution authority."""

from agent_storage.postgres.migration_types import Migration
from agent_storage.projection_work_schema import SCHEMA, pending_statement, routing_statements


def postgres_routing(source: str) -> tuple[str, ...]:
    statements = []
    for statement in routing_statements(source):
        statement = statement.replace("MAX(", "GREATEST(")
        statement = statement.replace(
            "needs_repair=(observed_through<wanted_through)",
            "needs_repair=CAST(observed_through<wanted_through AS INTEGER)",
        )
        if "INSERT OR IGNORE" in statement:
            statement = statement.replace("INSERT OR IGNORE", "INSERT") + " ON CONFLICT DO NOTHING"
        statements.append(statement)
    return tuple(statements)


_SOURCE = """SELECT NEW.deployment_namespace AS deployment_namespace,NEW.task_id::text AS task_id,
 NEW.event_id::text AS event_id,NEW.task_sequence AS task_sequence,NEW.event_type AS event_type,
 NEW.replay_command_kind AS command_kind,NEW.replay_run_id AS run_id,
 NEW.replay_internal_continuation::integer AS internal,NULL::text AS selected_version"""
_TASK_SOURCE = """SELECT NEW.deployment_namespace AS deployment_namespace,
 NEW.task_id::text AS task_id,
 NEW.next_event_sequence-1 AS task_sequence,NULL::text AS selected_version"""

TASK_PROJECTION_WORK_MIGRATION = Migration(
    version=68,
    name="durable_bounded_task_projection_work",
    statements=tuple(
        statement.strip()
        .replace("INTEGER", "BIGINT")
        .replace("retry_at REAL", "retry_at DOUBLE PRECISION")
        for statement in SCHEMA.split(";")
        if statement.strip()
    )
    + (
        "CREATE FUNCTION wake_projection_work_task() RETURNS trigger AS $$ BEGIN "
        # Coordinate first version enable with canonical READ COMMITTED Task insertion.
        # Bootstrap takes no source/Task lock, and GET never adopts history.
        "PERFORM pg_advisory_xact_lock(68,hashtext(NEW.deployment_namespace)); "
        + pending_statement(_TASK_SOURCE).replace("MAX(", "GREATEST(")
        + "; RETURN NEW; END; $$ LANGUAGE plpgsql VOLATILE",
        "CREATE TRIGGER agent_tasks_projection_work_insert AFTER INSERT ON agent_tasks "
        "FOR EACH ROW EXECUTE FUNCTION wake_projection_work_task()",
        "CREATE FUNCTION route_task_projection_work() RETURNS trigger AS $$ BEGIN "
        "IF NEW.task_id IS NULL OR NEW.task_sequence IS NULL THEN RETURN NEW; END IF; "
        "IF NOT NEW.replay_header_ready THEN "
        + pending_statement(_SOURCE).replace("MAX(", "GREATEST(")
        + "; RETURN NEW; END IF; "
        # Serialize routing per Task/version. Task source assignment already owns the source lock;
        # maintenance never acquires source-row locks, so there is no reverse lock order.
        + ";".join(postgres_routing(_SOURCE))
        + "; RETURN NEW; END; $$ LANGUAGE plpgsql",
        """CREATE TRIGGER session_events_projection_work_insert AFTER INSERT ON session_events
           FOR EACH ROW EXECUTE FUNCTION route_task_projection_work()""",
        """CREATE TRIGGER session_events_projection_work_assign
           AFTER UPDATE OF task_id,task_sequence,replay_header_ready ON session_events
           FOR EACH ROW EXECUTE FUNCTION route_task_projection_work()""",
    ),
)
