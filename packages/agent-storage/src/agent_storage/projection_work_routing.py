"""Source-owned queue selection and bounded reuse of scalar route repair."""

from agent_storage.projection_work_schema import routing_statements

ORDINARY = "ag-ui-v1"
COVERAGE = "ag-ui-v1-coverage"
BOOTSTRAP_SOURCE = """SELECT :namespace AS deployment_namespace,:task_id AS task_id,
 :through AS task_sequence,:version AS selected_version"""
PG_BOOTSTRAP_SOURCE = """SELECT %(namespace)s::text AS deployment_namespace,
 %(task_id)s::text AS task_id,%(through)s::bigint AS task_sequence,
 %(version)s::text AS selected_version"""
PENDING = """SELECT w.*,COALESCE((SELECT h.through_sequence FROM task_projection_heads h
 WHERE h.deployment_namespace=w.deployment_namespace AND h.task_id=w.task_id
 AND h.anchor_key=w.anchor_key AND h.projector_version=w.projector_version LIMIT 1),-1)
 AS after_sequence
 FROM (SELECT deployment_namespace,task_id,anchor_key,projector_version,run_id,
 anchor_sequence,requested_through,revision,closed_through FROM task_projection_work
 WHERE deployment_namespace=? AND projector_version=? AND pending=1
 AND problem_code IS NULL AND (task_id,anchor_key)>(?,?)
 ORDER BY task_id,anchor_key LIMIT ?) w
 ORDER BY w.task_id,w.anchor_key"""


def privacy_frontier(task: str, *, postgres: bool = False) -> str:
    namespace = f"c.deployment_namespace={task}.deployment_namespace AND " if postgres else ""
    return (
        "COALESCE((SELECT MIN(c.task_sequence) FROM task_replay_coverage_privacy c "
        f"WHERE {namespace}c.task_id={task}.task_id),-1)"
    )


def task_version(task: str, *, postgres: bool = False) -> str:
    return (
        f"CASE WHEN {privacy_frontier(task, postgres=postgres)}>=0 "
        f"THEN '{COVERAGE}' ELSE '{ORDINARY}' END"
    )


def classified_source(source: str, *, postgres: bool = False) -> str:
    # Other explicitly enabled projector versions retain their existing contract.
    # Only the two AG-UI queues are mutually exclusive, based on source presence.
    key = "s.task_id::uuid" if postgres else "s.task_id"
    namespace = "s.deployment_namespace" if postgres else "t.namespace"
    owner = "t.deployment_namespace" if postgres else "t.namespace"
    return (
        "SELECT s.*,p.projector_version AS routed_version,"
        f"{privacy_frontier('t', postgres=postgres)} AS privacy_frontier "
        f"FROM ({source}) s JOIN agent_tasks t ON t.task_id={key} "
        f"AND {owner}=s.deployment_namespace "
        "JOIN task_projection_work_projectors p ON "
        f"p.deployment_namespace={namespace} AND p.deployment_namespace=s.deployment_namespace "
        "AND p.enabled=1 AND (s.selected_version IS NULL "
        "OR p.projector_version=s.selected_version) "
        f"AND (p.projector_version NOT IN ('{ORDINARY}','{COVERAGE}') "
        f"OR p.projector_version={task_version('t', postgres=postgres)})"
    )


def selected_source(source: str, *, postgres: bool = False) -> str:
    routed = classified_source(source, postgres=postgres)
    # Task insertion sources have no Event fields; use this only for scalar headers.
    return (
        "SELECT deployment_namespace,task_id,event_id,task_sequence,event_type,command_kind,"
        f"run_id,internal,routed_version AS selected_version FROM ({routed}) classified"
    )


def classified_pending(source: str, *, postgres: bool = False) -> str:
    routed = classified_source(source, postgres=postgres)
    maximum = "GREATEST" if postgres else "MAX"
    return (
        "INSERT INTO task_projection_work_routes "
        "(deployment_namespace,task_id,projector_version,wanted_through,needs_repair) "
        f"SELECT deployment_namespace,task_id,routed_version,task_sequence,1 FROM ({routed}) s "
        "WHERE true ON CONFLICT(deployment_namespace,task_id,projector_version) DO UPDATE SET "
        f"wanted_through={maximum}(task_projection_work_routes.wanted_through,excluded.wanted_through),"
        "needs_repair=1"
    )


def activate_privacy(
    source: str, *, postgres: bool = False, preclassified: bool = False,
) -> str:
    routed = source if preclassified else classified_source(source, postgres=postgres)
    return (
        "UPDATE task_projection_work_routes SET observed_through=-1,active_anchor_key=NULL,"
        "needs_repair=1,privacy_frontier=(SELECT s.privacy_frontier "
        f"FROM ({routed}) s WHERE "
        "s.deployment_namespace=task_projection_work_routes.deployment_namespace "
        "AND s.task_id=task_projection_work_routes.task_id "
        "AND s.routed_version=task_projection_work_routes.projector_version) "
        "WHERE privacy_frontier=-1 "
        "AND (deployment_namespace,task_id,projector_version) IN "
        f"(SELECT deployment_namespace,task_id,routed_version FROM ({routed}) s "
        f"WHERE routed_version='{COVERAGE}' AND privacy_frontier>=0)"
    )


def routed_statements(
    source: str, *, postgres: bool = False, legacy_scalar_source: bool = False,
    preclassified: bool = False,
) -> tuple[str, ...]:
    # ponytail: legacy mode freezes v98 SQL; upgrades replace its trigger additively.
    statements = list(routing_statements(
        source if preclassified else selected_source(source, postgres=postgres),
        correlate_source=not legacy_scalar_source,
    ))
    statements.insert(1, activate_privacy(source, postgres=postgres, preclassified=preclassified))
    # Replaying after the one-time privacy flip revisits *each* canonical anchor,
    # including closed/ACKed legacy coverage rows. Never reset a true failure cap,
    # nor rewrite its captured target/closure. Each header remains a point-key step.
    for index, statement in enumerate(statements):
        if "INSERT OR IGNORE INTO task_projection_work " in statement:
            statements[index] = statement.replace("INSERT OR IGNORE", "INSERT") + (
                " ON CONFLICT(deployment_namespace,task_id,anchor_key,projector_version) "
                "DO UPDATE SET pending=1,revision=task_projection_work.revision+1,"
                "problem_code=CASE WHEN task_projection_work.dependency_wait=1 THEN NULL "
                "ELSE task_projection_work.problem_code END,"
                "retry_at=CASE WHEN task_projection_work.dependency_wait=1 THEN NULL "
                "ELSE task_projection_work.retry_at END,dependency_wait=0"
            )
    if postgres:
        statements = [
            statement.replace("MAX(", "GREATEST(").replace(
                "needs_repair=(observed_through<wanted_through)",
                "needs_repair=CAST(observed_through<wanted_through AS INTEGER)",
            )
            for statement in statements
        ]
    return tuple(statements)
