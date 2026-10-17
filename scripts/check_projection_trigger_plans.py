"""Native check with ZEBRA_TEST_POSTGRES_DSN pointing to an isolated test database."""

import os

import psycopg
from agent_core.application.session_bootstrap import (
    SessionBootstrapCommand,
    SessionBootstrapService,
)
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.ports.task_admission_transaction import TaskAdmissionRequest
from agent_storage.postgres import apply_postgres_migrations
from agent_storage.postgres.migrations import MIGRATIONS
from agent_storage.postgres.task_admission import PostgresTaskAdmissionTransaction
from psycopg.rows import dict_row


def check() -> None:
    dsn = os.environ["ZEBRA_TEST_POSTGRES_DSN"]
    frozen = {
        67: "828ae5c81a9faba1226b864635c189aefe0749fd210c703b25da6afd2dd01629",
        68: "a08e29f23387b57b0ed740702c65bedee740384226363e3d919f7689dc36201f",
        98: "a5c191da7be764473aa8083fe0af521e9cf412a03b48ebb89eb5a7b478fa8f46",
        100: "14c2495750845fa8c5604c5151193b64f087cb578552c97f91c22f8f3f89d8cc",
        102: "37cbac6fd32b61b0ca3ccbff095793189c03ae06bf9554bb929d28b095e54f9c",
    }
    assert {m.version: m.checksum for m in MIGRATIONS if m.version in frozen} == frozen
    apply_postgres_migrations(dsn)
    namespace = "projection-plan-check"
    admission = PostgresTaskAdmissionTransaction(dsn, deployment_namespace=namespace)
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        functions = connection.execute(
            "SELECT proname,proconfig FROM pg_proc WHERE oid IN "
            "('route_task_projection_work()'::regprocedure,"
            "'write_projection_source_metadata(text,uuid)'::regprocedure)"
        ).fetchall()
        assert len(functions) == 2
        assert all(f["proconfig"] == ["plan_cache_mode=force_generic_plan"] for f in functions)
        connection.execute("SET plan_cache_mode=force_custom_plan")
        for version in ("ag-ui-v1", "ag-ui-v1-coverage"):
            connection.execute(
                "INSERT INTO task_projection_work_projectors "
                "(deployment_namespace,projector_version,enabled) VALUES (%s,%s,1)",
                (namespace, version),
            )
        connection.commit()
        bootstrap = SessionBootstrapService().build(
            SessionBootstrapCommand(
                title="projection plan scope", user_input="no model", workspace_root="/tmp/check"
            )
        )
        request = TaskAdmissionRequest(
            events=tuple(bootstrap.events),
            session=bootstrap.session,
            workspace=rebuild_workspace(list(bootstrap.events)),
        )
        task = bootstrap.session.session_id
        admission.admit_in_transaction(connection, namespace, request)
        assert connection.execute("SHOW plan_cache_mode").fetchone()["plan_cache_mode"] == (
            "force_custom_plan"
        ), "function-local setting leaked to its caller"
        events = connection.execute(
            "SELECT task_sequence,projection_block_start,projection_metadata_ready "
            "FROM session_events WHERE deployment_namespace=%s AND task_id=%s "
            "ORDER BY task_sequence",
            (namespace, task),
        ).fetchall()
        assert events == [
            dict(task_sequence=i, projection_block_start=0, projection_metadata_ready=True)
            for i in range(3)
        ]
        routes = connection.execute(
            "SELECT projector_version,observed_through,wanted_through FROM "
            "task_projection_work_routes WHERE deployment_namespace=%s AND task_id=%s",
            (namespace, str(task)),
        ).fetchall()
        assert routes == [dict(projector_version="ag-ui-v1", observed_through=2, wanted_through=2)]
        # Explicit repair shares the function and must preserve the existing block.
        connection.execute(
            "SELECT write_projection_source_metadata(%s,%s)",
            (namespace, bootstrap.events[0].event_id),
        )
        assert connection.execute("SHOW plan_cache_mode").fetchone()["plan_cache_mode"] == (
            "force_custom_plan"
        )
        connection.commit()
        try:
            with connection.transaction():
                connection.execute(
                    "UPDATE session_events SET payload='{}'::jsonb "
                    "WHERE deployment_namespace=%s AND task_id=%s AND task_sequence=0",
                    (namespace, task),
                )
        except psycopg.errors.ObjectNotInPrerequisiteState:
            pass
        else:
            raise AssertionError("source business guard was weakened")
        assert connection.execute("SHOW plan_cache_mode").fetchone()["plan_cache_mode"] == (
            "force_custom_plan"
        )
        row = connection.execute(
            "SELECT first_task_sequence,last_task_sequence FROM task_projection_blocks "
            "WHERE deployment_namespace=%s AND task_id=%s",
            (namespace, task),
        ).fetchone()
        assert row == dict(first_task_sequence=0, last_task_sequence=2)
    print("native plans scoped; source/block/queue/repair guards and history preserved")


if __name__ == "__main__":
    check()
