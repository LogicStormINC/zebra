"""Seed a fresh synthetic corpus in a dedicated E1 PostgreSQL database."""

import argparse
import json
import os
import sys
from uuid import uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict


def populate(dsn: str, task_count: int) -> dict[str, str | int]:
    params = conninfo_to_dict(dsn)
    if (
        params.get("host") not in {"localhost", "127.0.0.1"}
        or not params.get("dbname", "").startswith("zebra_e1_corpus_")
        or params.get("service")
        or params.get("hostaddr") not in {None, "127.0.0.1"}
        or not 1 <= task_count <= 10_000
    ):
        raise ValueError("expected an explicit, dedicated loopback E1 corpus database")
    namespace = f"e1-corpus-{uuid4().hex}"
    print(f"seeding {namespace}", file=sys.stderr, flush=True)
    with psycopg.connect(dsn, options="-c statement_timeout=60000") as connection:
        for offset in range(0, task_count, 50):
            task_ids = [uuid4() for _ in range(min(50, task_count - offset))]
            with connection.transaction():
                connection.execute(
                    """INSERT INTO session_streams
                       (deployment_namespace,session_id,current_version)
                       SELECT %s,id,99 FROM unnest(%s::uuid[]) id""",
                    (namespace, task_ids),
                )
                connection.execute(
                    """INSERT INTO session_projections
                       (deployment_namespace,session_id,title,status,created_at,updated_at,
                        current_sequence)
                       SELECT %s,id,'E1 synthetic Task','created',now(),now(),99
                       FROM unnest(%s::uuid[]) id""",
                    (namespace, task_ids),
                )
                connection.execute(
                    """INSERT INTO agent_tasks
                       (deployment_namespace,task_id,root_session_id,active_segment_id,
                        created_at,updated_at,event_position_state)
                       SELECT %s,id,id,id,now(),now(),'ready' FROM unnest(%s::uuid[]) id""",
                    (namespace, task_ids),
                )
                connection.execute(
                    """INSERT INTO execution_segments
                       (deployment_namespace,session_id,task_id,segment_index,visibility,
                        event_position_source_ready)
                       SELECT %s,id,id,0,'internal',true FROM unnest(%s::uuid[]) id""",
                    (namespace, task_ids),
                )
                connection.execute(
                    """INSERT INTO session_events
                       (deployment_namespace,event_id,session_id,sequence,event_type,payload,
                        actor,created_at)
                       SELECT %s,gen_random_uuid(),id,n,
                              CASE WHEN n=0 THEN 'session_created' ELSE 'session_title_updated' END,
                              '{"title":"E1 synthetic Task"}','system',now()
                       FROM unnest(%s::uuid[]) id CROSS JOIN generate_series(0,99) n
                       ORDER BY id,n""",
                    (namespace, task_ids),
                )
        tasks, events, indexes = connection.execute(
            """SELECT (SELECT count(*) FROM agent_tasks WHERE deployment_namespace=%s
                       AND event_position_state='ready' AND next_event_sequence=100),
                      (SELECT count(*) FROM session_events WHERE deployment_namespace=%s
                       AND task_id=session_id AND task_sequence=sequence),
                      (SELECT count(*) FROM task_event_index i JOIN session_events e
                       ON (i.deployment_namespace,i.event_id)=(e.deployment_namespace,e.event_id)
                       WHERE i.deployment_namespace=%s
                       AND (i.task_id,i.task_sequence,i.segment_id,i.segment_sequence)
                         =(e.task_id,e.task_sequence,e.session_id,e.sequence))""",
            (namespace, namespace, namespace),
        ).fetchone()
    if (tasks, events, indexes) != (task_count, task_count * 100, task_count * 100):
        raise RuntimeError(f"corpus coordinates incomplete for {namespace}")
    return {"namespace": namespace, "tasks": tasks, "events": events, "indexes": indexes}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=int, default=10_000)
    args = parser.parse_args()
    print(json.dumps(populate(os.environ["ZEBRA_E1_CORPUS_DSN"], args.tasks)))


if __name__ == "__main__":
    main()
