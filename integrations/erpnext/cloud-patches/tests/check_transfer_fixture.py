"""Explicitly disposable QA database fixtures; never production acceptance."""

import json

import transfer_erp_database as t

# These are deliberately separate, explicitly QA-only phases around native dump/restore.
FIXTURE_TABLES = [
    {
        "name": "agent_tasks",
        "pk": ["deployment_namespace", "id"],
        "columns": [
            {"name": n, "generated": g}
            for n, g in [
                ("deployment_namespace", ""),
                ("id", ""),
                ("peer_id", ""),
                ("payload", ""),
                ("doc", ""),
                ("at", ""),
                ("computed", "s"),
            ]
        ],
    },
    {
        "name": "session_events",
        "pk": ["deployment_namespace", "id"],
        "columns": [
            {"name": n, "generated": ""} for n in ("deployment_namespace", "id", "task_id")
        ],
    },
    {
        "name": "host_grant_audit",
        "pk": ["deployment_namespace", "audit_id"],
        "columns": [{"name": n, "generated": ""} for n in ("deployment_namespace", "audit_id")],
    },
]
FIXTURE_DDL = (
    "\nCREATE TABLE public.agent_tasks(deployment_namespace text NOT N"
    "ULL,id bigint GENERATED ALWAYS AS IDENTITY,peer_id bigint,payloa"
    "d text,doc jsonb,at timestamptz,computed text GENERATED ALWAYS A"
    "S (upper(payload)) STORED,PRIMARY KEY(deployment_namespace,id));"
    "\nCREATE TABLE public.session_events(deployment_namespace text NO"
    "T NULL,id bigint PRIMARY KEY,task_id bigint);\nALTER TABLE public"
    ".agent_tasks ADD CONSTRAINT fixture_cycle_a FOREIGN KEY(peer_id)"
    " REFERENCES public.session_events(id) DEFERRABLE INITIALLY DEFER"
    "RED;\nALTER TABLE public.session_events ADD CONSTRAINT fixture_cy"
    "cle_b FOREIGN KEY(deployment_namespace,task_id) REFERENCES publi"
    "c.agent_tasks(deployment_namespace,id) DEFERRABLE INITIALLY DEFE"
    "RRED;\nCREATE TABLE public.host_grant_audit(deployment_namespace "
    "text NOT NULL,audit_id bigserial PRIMARY KEY);\nCREATE VIEW publi"
    "c.task_replay_coverage_privacy AS SELECT deployment_namespace,id"
    " FROM public.agent_tasks;\n"
)


def fixture(mode, path):
    import psycopg as psycopg
    from psycopg import sql

    cfg = json.loads(t.secure_read(path))

    def require_db(c, prefix):
        return t.require(c["dbname"].startswith(prefix), "fixture_database_identity")

    require_db(cfg["source"], "zebra_transfer_qa_source_")
    require_db(cfg["destination"], "erpnext_agent_qa_")
    t.require(cfg["source"]["host"] != cfg["destination"]["host"], "fixture_distinct_endpoints")
    worker = t.Worker(cfg)
    worker.src = worker.connect("source")
    worker.dst = worker.connect("destination")
    try:
        if mode == "identity":
            for name, conn in (("source", worker.src), ("destination", worker.dst)):
                conn.execute("SET TRANSACTION READ ONLY")
                info = worker.identity(conn)
                assert info["address"] == cfg[name]["host"] and "/" not in info["address"]
                assert info["database"] == cfg[name]["dbname"] and info["role"] == cfg[name]["user"]
            print(
                "PASS real native host(inet_server_addr()) identity matches exact"
                " configured server addresses"
            )
        elif mode == "prepare":
            for c in (worker.src, worker.dst):
                t.require(
                    c.execute(
                        "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.r"
                        "elnamespace WHERE n.nspname='public'"
                    ).fetchone()[0]
                    == 0,
                    "fixture_database_nonempty",
                )
            worker.src.execute(FIXTURE_DDL)
            worker.src.execute(
                (
                    "INSERT INTO public.agent_tasks(deployment_namespace,id,peer_id,p"
                    "ayload,doc,at) OVERRIDING SYSTEM VALUE VALUES(%s,42,7,%s,%s,%s)"
                ),
                [
                    "erpnext",
                    "tabs\tnewlines\nbackslash\\ literal\\N",
                    json.dumps({"null": None, "line": "a\nb", "unicode": "中文"}),
                    "2026-10-23 12:34:56.123456+08",
                ],
            )
            worker.src.execute(
                "INSERT INTO public.agent_tasks(deployment_namespace,id,payload) "
                "OVERRIDING SYSTEM VALUE VALUES ('erpnext-history',43,NULL),('erp"
                "next-continuation',44,'\\N')"
            )
            worker.src.execute("INSERT INTO public.session_events VALUES('erpnext',7,42)")
            worker.src.commit()
            print("PASS disposable fixture prepared; source data exists only in labeled QA server")
        elif mode in ("copy", "verify"):
            worker.src.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            expected = {tb["name"]: worker.row_hash(worker.src, tb) for tb in FIXTURE_TABLES}
            if mode == "copy":
                # Reuse production transaction/error boundary, then prove
                # injected failure rolled back.
                worker.manifest = {"catalog": {"tables": FIXTURE_TABLES}}
                worker.phase = "pre_restored"
                worker.alive = lambda: None
                original = worker.copy_table
                calls = []

                def failing(table):
                    calls.append(table["name"])
                    if len(calls) == 2:
                        raise RuntimeError("injected mid-copy failure")
                    original(table)

                worker.copy_table = failing
                try:
                    worker.copy_rows()
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("injected failure absent")
                assert not worker.durable and all(
                    worker.row_hash(worker.dst, tb)["count"] == 0 for tb in FIXTURE_TABLES
                )
                worker.dst.rollback()
                worker.copy_table = original
                worker.copy_rows()
                assert {
                    tb["name"]: worker.row_hash(worker.dst, tb) for tb in FIXTURE_TABLES
                } == expected
                worker.dst.rollback()
                print("PASS text COPY and rollback injection; restore native post-data next")
            else:
                assert {
                    tb["name"]: worker.row_hash(worker.dst, tb) for tb in FIXTURE_TABLES
                } == expected
                # Generated-column changes must be visible in the canonical full-row hash.
                table = FIXTURE_TABLES[0]
                before = worker.row_hash(worker.dst, table)
                worker.dst.execute(
                    "ALTER TABLE public.agent_tasks DROP COLUMN computed; ALTER TABLE"
                    " public.agent_tasks ADD COLUMN computed text GENERATED ALWAYS AS"
                    " (lower(payload)) STORED"
                )
                assert worker.row_hash(worker.dst, table) != before
                worker.dst.rollback()
                assert (
                    worker.dst.execute(
                        "SELECT count(*) FROM pg_constraint WHERE connamespace='public'::"
                        "regnamespace AND NOT convalidated"
                    ).fetchone()[0]
                    == 0
                )
                assert (
                    worker.dst.execute(
                        "SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid=i.index"
                        "relid WHERE c.relnamespace='public'::regnamespace AND (NOT indis"
                        "valid OR NOT indisready)"
                    ).fetchone()[0]
                    == 0
                )
                for table, column in (("agent_tasks", "id"), ("host_grant_audit", "audit_id")):
                    seq = worker.dst.execute(
                        "SELECT pg_get_serial_sequence(%s,%s)", ["public." + table, column]
                    ).fetchone()[0]
                    maximum = worker.dst.execute(
                        sql.SQL("SELECT max({}) FROM {}").format(
                            sql.Identifier(column), sql.Identifier("public", table)
                        )
                    ).fetchone()[0]
                    value, called = t.next_sequence(
                        {"start": 1, "increment": 1, "min": 1, "max": 2**63 - 1, "cycle": False},
                        maximum,
                    )
                    worker.dst.execute("SELECT setval(%s::regclass,%s,%s)", [seq, value, called])
                    observed = worker.dst.execute(
                        sql.SQL("SELECT last_value,is_called FROM {}").format(
                            sql.Identifier("public", seq.split(".")[-1])
                        )
                    ).fetchone()
                    assert observed == (value, called)
                worker.dst.commit()
                print(
                    "PASS native cyclic FK/identity/generated/hash and empty/nonempty"
                    " sequence roundtrip"
                )
        else:
            raise ValueError("unknown fixture phase")
    finally:
        worker.abort()
