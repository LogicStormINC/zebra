"""Derived scalar routing, installed explicitly after native source headers."""

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS task_projection_work_projectors (
 deployment_namespace TEXT NOT NULL, projector_version TEXT NOT NULL,
 enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
 bootstrap_after_task_id TEXT, bootstrap_complete INTEGER NOT NULL DEFAULT 0
 CHECK(bootstrap_complete IN (0,1)),
 PRIMARY KEY(deployment_namespace,projector_version));
CREATE INDEX IF NOT EXISTS projection_work_enabled ON task_projection_work_projectors
 (deployment_namespace,projector_version) WHERE enabled=1;
CREATE TABLE IF NOT EXISTS task_projection_work_routes (
 deployment_namespace TEXT NOT NULL, task_id TEXT NOT NULL, projector_version TEXT NOT NULL,
 observed_through INTEGER NOT NULL DEFAULT -1 CHECK(observed_through>=-1),
 wanted_through INTEGER NOT NULL DEFAULT -1 CHECK(wanted_through>=observed_through),
 active_anchor_key TEXT, needs_repair INTEGER NOT NULL DEFAULT 0 CHECK(needs_repair IN (0,1)),
 PRIMARY KEY(deployment_namespace,task_id,projector_version));
CREATE INDEX IF NOT EXISTS projection_work_repairs ON task_projection_work_routes
 (deployment_namespace,projector_version,task_id,observed_through,wanted_through)
 WHERE needs_repair=1;
CREATE TABLE IF NOT EXISTS task_projection_work (
 deployment_namespace TEXT NOT NULL, task_id TEXT NOT NULL, anchor_key TEXT NOT NULL,
 projector_version TEXT NOT NULL, run_id TEXT NOT NULL,
 anchor_sequence INTEGER NOT NULL CHECK(anchor_sequence>=0),
 requested_through INTEGER NOT NULL CHECK(requested_through>=anchor_sequence),
 revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>=1),
 closed_through INTEGER CHECK(closed_through=requested_through),
 problem_code TEXT CHECK(problem_code IN ('not_ready','integrity','budget','projection_failed')),
 problem_attempts INTEGER NOT NULL DEFAULT 0 CHECK(problem_attempts>=0), retry_at REAL,
 dependency_wait INTEGER NOT NULL DEFAULT 0 CHECK(dependency_wait IN (0,1)),
 pending INTEGER NOT NULL DEFAULT 1 CHECK(pending IN (0,1)),
 PRIMARY KEY(deployment_namespace,task_id,anchor_key,projector_version),
 CHECK(problem_code IS NOT NULL OR retry_at IS NULL),
 CHECK(dependency_wait=0 OR (problem_code IS NOT NULL
 AND problem_code='not_ready' AND retry_at IS NULL)));
CREATE INDEX IF NOT EXISTS projection_work_pending ON task_projection_work
 (deployment_namespace,projector_version,task_id,anchor_key,run_id,anchor_sequence,
 requested_through,revision,closed_through) WHERE pending=1 AND problem_code IS NULL;
CREATE INDEX IF NOT EXISTS projection_work_retry ON task_projection_work
 (deployment_namespace,projector_version,retry_at,task_id,anchor_key)
 WHERE pending=1 AND problem_code IS NOT NULL AND retry_at IS NOT NULL;
"""

KEY = "deployment_namespace,task_id,anchor_key,projector_version"
ROUTE_KEY = "deployment_namespace,task_id,projector_version"
SOURCE = """SELECT :namespace AS deployment_namespace,:task_id AS task_id,
 :event_id AS event_id,:task_sequence AS task_sequence,:event_type AS event_type,
 :command_kind AS command_kind,:run_id AS run_id,:internal AS internal,
 :version AS selected_version"""
BOOTSTRAP_ENQUEUE = """INSERT INTO task_projection_work_routes
 (deployment_namespace,task_id,projector_version,wanted_through,needs_repair)
 VALUES (?,?,?,?,1) ON CONFLICT(deployment_namespace,task_id,projector_version)
 DO UPDATE SET wanted_through=MAX(task_projection_work_routes.wanted_through,
 excluded.wanted_through),
 needs_repair=CASE WHEN task_projection_work_routes.observed_through<
 MAX(task_projection_work_routes.wanted_through,excluded.wanted_through) THEN 1
 ELSE task_projection_work_routes.needs_repair END"""


def pending_statement(source: str) -> str:
    """Unready source records a durable scalar repair-needed row, not a Run."""
    return (
        "INSERT INTO task_projection_work_routes "
        "(deployment_namespace,task_id,projector_version,wanted_through,needs_repair) "
        "SELECT s.deployment_namespace,s.task_id,p.projector_version,s.task_sequence,1 "
        f"FROM ({source}) s JOIN task_projection_work_projectors p "
        "ON p.deployment_namespace=s.deployment_namespace AND p.enabled=1 "
        "AND (s.selected_version IS NULL OR p.projector_version=s.selected_version) "
        "WHERE true ON CONFLICT(deployment_namespace,task_id,projector_version) "
        "DO UPDATE SET wanted_through=MAX(task_projection_work_routes.wanted_through,"
        "excluded.wanted_through),needs_repair=1"
    )


def routing_statements(source: str, *, correlate_source: bool = False) -> tuple[str, ...]:
    """Same point-key routing in source triggers and explicit bounded maintenance."""
    enabled = (
        f"FROM ({source}) s JOIN task_projection_work_projectors p "
        "ON p.deployment_namespace=s.deployment_namespace AND p.enabled=1 "
        "AND (s.selected_version IS NULL OR p.projector_version=s.selected_version)"
    )
    current = (
        enabled + " JOIN task_projection_work_routes r ON "
        "r.deployment_namespace=s.deployment_namespace AND r.task_id=s.task_id "
        "AND r.projector_version=p.projector_version "
    )
    executable = (
        "COALESCE((s.event_type='session_command_accepted' AND s.internal=0 "
        "AND s.command_kind IN ('run','resume','message')),false)"
    )
    contiguous = "r.observed_through=s.task_sequence-1"
    active = (
        "SELECT r.deployment_namespace,r.task_id,r.active_anchor_key,r.projector_version "
        + current
        + f"WHERE {contiguous} AND "
    )
    # Dependency state is independent of the true failure cap; wake never resets that budget.
    wake = (
        "problem_code=CASE WHEN dependency_wait=1 THEN NULL ELSE problem_code END,"
        "retry_at=CASE WHEN dependency_wait=1 THEN NULL ELSE retry_at END,dependency_wait=0,"
    )
    # ponytail: the default freezes v68 SQL; never alter its historical output.
    scalar_source = f"FROM ({source}) s"
    if correlate_source:
        scalar_source += (
            " WHERE s.deployment_namespace=task_projection_work_routes.deployment_namespace"
            " AND s.task_id=task_projection_work_routes.task_id"
            " AND (s.selected_version IS NULL OR "
            "s.selected_version=task_projection_work_routes.projector_version)"
        )
    return (
        pending_statement(source),
        "UPDATE task_projection_work SET requested_through=(SELECT s.task_sequence-1 "
        + current
        + "WHERE r.active_anchor_key=task_projection_work.anchor_key "
        "AND r.deployment_namespace=task_projection_work.deployment_namespace "
        "AND r.task_id=task_projection_work.task_id "
        "AND r.projector_version=task_projection_work.projector_version), "
        "closed_through=(SELECT s.task_sequence-1 "
        + current
        + "WHERE r.active_anchor_key=task_projection_work.anchor_key "
        "AND r.deployment_namespace=task_projection_work.deployment_namespace "
        "AND r.task_id=task_projection_work.task_id "
        "AND r.projector_version=task_projection_work.projector_version), "
        + wake
        + f"revision=revision+1,pending=1 WHERE ({KEY}) IN ({active}{executable}) "
        "AND closed_through IS NULL",
        "UPDATE task_projection_work SET requested_through=requested_through+1, "
        + wake
        + f"revision=revision+1,pending=1 WHERE ({KEY}) IN ({active}NOT ({executable})) "
        "AND closed_through IS NULL",
        "INSERT OR IGNORE INTO task_projection_work "
        f"({KEY},run_id,anchor_sequence,requested_through) "
        "SELECT s.deployment_namespace,s.task_id,s.event_id,p.projector_version,s.run_id,"
        "s.task_sequence,s.task_sequence "
        + current
        + f"WHERE {contiguous} AND {executable} AND s.run_id IS NOT NULL",
        "UPDATE task_projection_work_routes SET active_anchor_key=CASE WHEN "
        f"(SELECT {executable} {scalar_source}) THEN "
        f"(SELECT CASE WHEN s.run_id IS NOT NULL THEN s.event_id END {scalar_source}) "
        "ELSE active_anchor_key END,observed_through=observed_through+1 "
        f"WHERE ({ROUTE_KEY}) IN (SELECT r.deployment_namespace,r.task_id,r.projector_version "
        + current
        + f"WHERE {contiguous})",
        "UPDATE task_projection_work_routes SET needs_repair=(observed_through<wanted_through) "
        f"WHERE ({ROUTE_KEY}) IN (SELECT s.deployment_namespace,s.task_id,p.projector_version "
        + enabled
        + ")",
    )


def initialize_projection_work(connection: sqlite3.Connection) -> None:
    """DDL/hooks only; no source scan, registration, adoption, or implicit repair."""
    from agent_storage.projection_work_routing import (
        activate_privacy,
        classified_pending,
        routed_statements,
    )
    from agent_storage.task_projection_coverage_cells_schema import COVERAGE_PRIVACY

    for statement in SCHEMA.split(";"):
        if statement.strip():
            connection.execute(statement)
    upgraded = "dependency_wait" not in {
        row[1] for row in connection.execute("PRAGMA table_info(task_projection_work)")
    }
    if upgraded:
        # Metadata-only upgrade; ambiguous legacy problems stay fail-closed for operator retry.
        connection.execute(
            "ALTER TABLE task_projection_work ADD COLUMN dependency_wait INTEGER NOT NULL DEFAULT 0"
        )
    if "privacy_frontier" not in {
        row[1] for row in connection.execute("PRAGMA table_info(task_projection_work_routes)")
    }:
        connection.execute(
            "ALTER TABLE task_projection_work_routes ADD COLUMN privacy_frontier INTEGER "
            "NOT NULL DEFAULT -1 CHECK(privacy_frontier>=-1)"
        )
        connection.execute(
            "UPDATE task_projection_work_projectors SET bootstrap_after_task_id=NULL,"
            "bootstrap_complete=0"
        )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS projection_work_task_scope ON agent_tasks(namespace,task_id)"
    )
    task_source = """SELECT NEW.namespace AS deployment_namespace,NEW.task_id AS task_id,
     NEW.next_event_sequence-1 AS task_sequence,NULL AS selected_version"""
    connection.execute("DROP TRIGGER IF EXISTS agent_tasks_projection_work_insert")
    connection.execute(f"""CREATE TRIGGER agent_tasks_projection_work_insert
     AFTER INSERT ON agent_tasks BEGIN {classified_pending(task_source, profiles=True)}; END""")
    source = """SELECT namespace AS deployment_namespace,NEW.task_id AS task_id,
     NEW.event_id AS event_id,NEW.task_sequence AS task_sequence,NEW.event_type AS event_type,
     NEW.replay_command_kind AS command_kind,NEW.replay_run_id AS run_id,
     NEW.replay_internal_continuation AS internal,NULL AS selected_version
     FROM agent_tasks WHERE task_id=NEW.task_id"""
    # SQLite does not specify sibling AFTER-trigger order. Ensure the existing
    # source-guarded locator first; never route a first strict marker as ordinary.
    locate = f"""INSERT OR IGNORE INTO task_replay_coverage_privacy
     SELECT event_id,task_id,task_sequence FROM session_events WHERE event_id=NEW.event_id
     AND task_id IS NOT NULL AND task_sequence IS NOT NULL AND {COVERAGE_PRIVACY};"""
    body = locate + ";\n".join(routed_statements(source, profiles=True)) + ";"
    for name, operation in (
        ("insert", "INSERT"),
        ("assign", "UPDATE OF task_id,task_sequence,replay_header_ready"),
    ):
        connection.execute(f"DROP TRIGGER IF EXISTS session_events_work_{name}")
        connection.execute(f"""CREATE TRIGGER session_events_work_{name}
         AFTER {operation} ON session_events WHEN NEW.task_id IS NOT NULL
         AND NEW.task_sequence IS NOT NULL AND NEW.replay_header_ready=1
         BEGIN {body} END""")
        connection.execute(f"DROP TRIGGER IF EXISTS session_events_work_pending_{name}")
        connection.execute(f"""CREATE TRIGGER session_events_work_pending_{name}
         AFTER {operation} ON session_events WHEN NEW.task_id IS NOT NULL
         AND NEW.task_sequence IS NOT NULL AND NEW.replay_header_ready=0
         BEGIN {locate}{classified_pending(source, profiles=True)};
         {activate_privacy(source, profiles=True)}; END""")
    connection.execute("DROP TRIGGER IF EXISTS coverage_privacy_projection_work_insert")
    locator_source = """SELECT namespace AS deployment_namespace,task_id,
     next_event_sequence-1 AS task_sequence,NULL AS selected_version
     FROM agent_tasks WHERE task_id=NEW.task_id"""
    connection.execute(f"""CREATE TRIGGER coverage_privacy_projection_work_insert
     AFTER INSERT ON task_replay_coverage_privacy BEGIN
     {classified_pending(locator_source, profiles=True)};
     {activate_privacy(locator_source, profiles=True)}; END""")
