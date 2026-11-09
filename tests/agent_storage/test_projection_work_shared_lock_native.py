import os
from uuid import uuid4

import psycopg
import pytest
from agent_storage.postgres.agui_profile_routing_migration import AGUI_PROFILE_ROUTING_MIGRATION
from agent_storage.postgres.migration_runner import apply_postgres_migrations
from agent_storage.postgres.projection_work_shared_lock_migration import (
    PROJECTION_WORK_SHARED_LOCK_MIGRATION,
)
from psycopg import sql
from psycopg.conninfo import make_conninfo

from tests.agent_storage.test_postgres_projection_source_metadata import NS


def seed(c):
    sid = uuid4()
    c.execute("INSERT INTO session_streams VALUES (%s,%s,0)", (NS, sid))
    c.execute(
        """INSERT INTO session_projections
        (deployment_namespace,session_id,title,status,created_at,updated_at,current_sequence)
        VALUES (%s,%s,'lock probe','created',now(),now(),0)""",
        (NS, sid),
    )
    c.execute(
        """INSERT INTO agent_tasks
        (deployment_namespace,task_id,root_session_id,active_segment_id,created_at,updated_at,
         next_event_sequence,event_position_state)
        VALUES (%s,%s,%s,%s,now(),now(),0,'ready')""",
        (NS, sid, sid, sid),
    )

    c.execute(
        """INSERT INTO execution_segments
        (deployment_namespace,session_id,task_id,segment_index,visibility,
         event_position_source_cursor,event_position_source_ready)
        VALUES (%s,%s,%s,0,'internal',-1,true)""",
        (NS, sid, sid),
    )


def test_projection_lock_probe():
    base = os.environ["ZEBRA_TEST_POSTGRES_DSN"]
    schema = "ha_projection_lock_" + uuid4().hex
    with psycopg.connect(base, autocommit=True) as admin:
        assert admin.execute("select current_database(), current_user").fetchone() == (
            "ha_qa",
            "ha_qa",
        )
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        dsn = make_conninfo(base, options=f"-c search_path={schema},public")
        try:
            apply_postgres_migrations(dsn)
            with psycopg.connect(dsn) as c:
                c.execute(AGUI_PROFILE_ROUTING_MIGRATION.statements[0])
            with psycopg.connect(dsn) as a, psycopg.connect(dsn) as b:
                seed(a)
                b.execute("SET LOCAL lock_timeout='250ms'")
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    seed(b)
                a.rollback()
                b.rollback()
            with psycopg.connect(dsn) as c:
                c.execute(PROJECTION_WORK_SHARED_LOCK_MIGRATION.statements[0])
            with (
                psycopg.connect(dsn) as a,
                psycopg.connect(dsn) as b,
                psycopg.connect(dsn) as config,
            ):
                seed(a)
                b.execute("SET LOCAL lock_timeout='250ms'")
                seed(b)
                config.execute("SET LOCAL lock_timeout='250ms'")
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    config.execute("SELECT pg_advisory_xact_lock(68,hashtext(%s))", (NS,))
                config.rollback()
                a.commit()
                b.commit()
                config.execute("SELECT pg_advisory_xact_lock(68,hashtext(%s))", (NS,))
                b.execute("SET LOCAL lock_timeout='250ms'")
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    seed(b)
                b.rollback()
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
