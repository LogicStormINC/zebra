"""Source-trigger classification is bounded once; old migration SQL stays frozen."""

from agent_storage.postgres.migrations import MIGRATIONS

from tests.agent_storage.test_postgres_scalar_task_replay_headers import scratch as _scratch_fixture

scratch = _scratch_fixture


def test_latest_route_trigger_classifies_source_once():
    statement = next(
        statement
        for migration in reversed(MIGRATIONS)
        for statement in migration.statements
        if "CREATE OR REPLACE FUNCTION route_task_projection_work()" in statement
    )
    # Readiness keeps its existing pending/privacy branch; the ready branch should
    # contain one classifier instead of expanding it into each routing statement.
    ready = statement.split("RETURN NEW; END IF;", 2)[-1]
    assert ready.count("task_replay_coverage_privacy") <= 2, (
        "canonical source privacy is reclassified in each routing statement"
    )


def test_historical_route_migrations_remain_byte_identical():
    expected = {
        68: "a08e29f23387b57b0ed740702c65bedee740384226363e3d919f7689dc36201f",
        98: "a5c191da7be764473aa8083fe0af521e9cf412a03b48ebb89eb5a7b478fa8f46",
        100: "14c2495750845fa8c5604c5151193b64f087cb578552c97f91c22f8f3f89d8cc",
    }
    assert {m.version: m.checksum for m in MIGRATIONS if m.version in expected} == expected


def test_native_mid_route_disable_keeps_enabled_guard(tmp_path, scratch):
    from uuid import uuid4

    from psycopg.types.json import Jsonb

    from tests.agent_storage.projection_work_test_support import QueueFixture

    queue = QueueFixture("postgres", tmp_path, scratch)
    queue.install()
    with queue.connect() as connection:
        for statement in MIGRATIONS[-1].statements:
            connection.execute(statement)
    queue.store("ag-ui-v1-coverage").enable_projection_work()
    with queue.connect() as connection:
        connection.execute("""CREATE FUNCTION disable_mid_route() RETURNS trigger AS $$ BEGIN
          UPDATE task_projection_work_projectors SET enabled=0
          WHERE deployment_namespace=NEW.deployment_namespace
            AND projector_version=NEW.projector_version;
          RETURN NEW; END; $$ LANGUAGE plpgsql""")
        connection.execute("""CREATE TRIGGER disable_mid_route BEFORE INSERT
          ON task_projection_work_routes FOR EACH ROW EXECUTE FUNCTION disable_mid_route()""")
        connection.execute(
            "INSERT INTO session_events (deployment_namespace,event_id,session_id,sequence,"
            "event_type,payload,actor,task_id,task_sequence,event_bytes_bound) "
            "VALUES (%s,%s,%s,0,'task_prepared',%s,'system',%s,0,1024)",
            (queue.namespace, uuid4(), queue.task, Jsonb({"coverage_admission": None}), queue.task),
        )
        row = connection.execute(
            "SELECT privacy_frontier FROM task_projection_work_routes"
        ).fetchone()
        assert row["privacy_frontier"] == -1, "classification replaced the live enabled check"
        count = connection.execute("SELECT COUNT(*) AS n FROM task_projection_work").fetchone()["n"]
        assert count == 0
