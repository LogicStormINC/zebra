#!/usr/bin/env python3
"""Runnable assertions. Default: no database writes. --fixture commands: QA only.

Run with Python stdlib, then in exact pinned105 API image for psycopg SQL checks.
The explicitly disposable fixture phases require dedicated QA databases and native
pg_dump/psql pre/postdata between phases; see ERP_DATABASE_TRANSFER.md.
"""

import contextlib
import copy
import io
import json
import subprocess
import sys
import tempfile
import zipfile
from datetime import UTC as UTC
from datetime import datetime as datetime
from datetime import timezone as timezone
from pathlib import Path

import transfer_erp_database as t
import transfer_host as host_module
import transfer_worker_entry as worker_entry
from transfer_worker_bundle import WORKER_MAIN, WORKER_MODULES, worker_bundle


def refuses(fn, code):
    try:
        fn()
    except t.Refusal as error:
        assert str(error) == code, (str(error), code)
    else:
        raise AssertionError("accepted " + code)


def sample_catalog():
    tables = []
    for name in t.TABLES:
        cols = [{"name": "id", "generated": "", "identity": ""}]
        if name in t.DEFINITIONS:
            cols.extend(
                {"name": c, "generated": "", "identity": ""}
                for c in ("namespace_id", "authority_issuer")
            )
        elif name != "zebra_schema_migrations":
            cols.append({"name": "deployment_namespace", "generated": "", "identity": ""})
        if name == "governed_memory_records":
            cols.append({"name": "search_vector", "generated": "s", "identity": ""})
        tables.append(
            {
                "name": name,
                "columns": cols,
                "kind": "r",
                "partition": False,
                "pk": ["id"],
                "rls": False,
                "force_rls": False,
            }
        )
    return {
        "tables": tables,
        "views": [{"name": "task_replay_coverage_privacy", "definition": "SELECT 1"}],
        "other_relations": [],
        "routines": [{"name": n, "security_definer": False} for n in t.ROUTINES],
        "triggers": [{"table": a, "name": b} for a, b in t.TRIGGERS],
        "policies": [],
        "user_types": [],
        "sequences": [
            dict(
                name=a + "_seq",
                table=a,
                column=b,
                start=1,
                increment=1,
                min=1,
                max=100,
                cycle=False,
            )
            for a, b in sorted(t.SEQUENCE_OWNERS)
        ],
        "extensions": [{"name": "plpgsql", "version": "1.0"}],
        "constraints": [{"validated": True}],
        "indexes": [{"valid": True, "ready": True}],
    }


def checks():
    assert (
        "'address',host(inet_server_addr())" in t.IDENTITY_SQL
        and "inet_server_addr()::text" not in t.IDENTITY_SQL
    )
    m = sample_catalog()
    t.validate_catalog(m)
    cases = [
        ("relation_inventory", lambda x: x["tables"].append(copy.deepcopy(x["tables"][0]))),
        ("relation_inventory", lambda x: x["tables"][0].update(name="foreign_tenant")),
        ("table_shape", lambda x: x["tables"][0].update(pk=[])),
        ("primary_key", lambda x: x["tables"][0].update(pk=["missing"])),
        ("table_shape", lambda x: x["tables"][0].update(partition=True)),
        ("generated_inventory", lambda x: x["tables"][0]["columns"][0].update(generated="s")),
        ("view_inventory", lambda x: x["views"][0].update(name="unknown_view")),
        ("sequence_inventory", lambda x: x["sequences"][0].update(column="unknown")),
        ("sequence_parameters", lambda x: x["sequences"][0].update(cycle=True)),
        ("routine_inventory", lambda x: x["routines"][0].update(security_definer=True)),
        ("trigger_inventory", lambda x: x["triggers"].pop()),
        ("invalid_schema", lambda x: x["indexes"][0].update(valid=False)),
        ("invalid_schema", lambda x: x["constraints"][0].update(validated=False)),
    ]
    for code, change in cases:
        altered = copy.deepcopy(m)
        change(altered)
        refuses(lambda *, altered=altered: t.validate_catalog(altered), code)
    seq = m["sequences"][0]
    assert t.next_sequence(seq, None) == (1, False)
    assert t.next_sequence(seq, 1) == (1, True)
    assert t.next_sequence(seq, 99) == (99, True)
    refuses(lambda: t.next_sequence(seq, 100), "sequence_exhausted")
    assert t.NAMESPACES == ("erpnext", "erpnext-history", "erpnext-continuation")
    assert t.DEFINITION == ("erpnext", "https://erpnext.zebra.local")
    expected = [(v, "migration_" + str(v), "a" * 64) for v in list(range(1, 104)) + [105]]
    t.validate_ledger(expected, expected)
    for field, value in ((0, 104), (1, "changed_native_name"), (2, "b" * 64)):
        altered = [list(r) for r in expected]
        altered[0][field] = value
        refuses(
            lambda *, altered=altered: t.validate_ledger(altered, expected),
            ("source_ledger_not_canonical105"),
        )
    # The approval comparison precedes every target connection or mutation.
    worker = object.__new__(t.Worker)
    worker.phase = "snapshot"
    worker.manifest = {"catalog": m, "migrations": [[105, "native", "a" * 64]]}
    worker.hashes = {"agent_tasks": {"count": 1, "sha256": "b" * 64}}
    for change in ("pk", "generated", "version", "checksum", "count", "hash"):
        approved = {
            "manifest": copy.deepcopy(worker.manifest),
            "hashes": copy.deepcopy(worker.hashes),
        }
        if change == "pk":
            approved["manifest"]["catalog"]["tables"][0]["pk"] = ["deployment_namespace"]
        if change == "generated":
            approved["manifest"]["catalog"]["tables"][0]["columns"][0]["generated"] = "s"
        if change == "version":
            approved["manifest"]["migrations"][0][0] = 106
        if change == "checksum":
            approved["manifest"]["migrations"][0][2] = "c" * 64
        if change == "count":
            approved["hashes"]["agent_tasks"]["count"] = 2
        if change == "hash":
            approved["hashes"]["agent_tasks"]["sha256"] = "d" * 64
        refuses(lambda *, approved=approved: worker.target(approved), "approval_drift")

    # Target trust boundaries fail before a target commit or DDL.
    class AuthenticationFailure(Exception):
        sqlstate = "28P01"

    class FakePG:
        OperationalError = AuthenticationFailure

        def connect(self, **kwargs):
            raise AuthenticationFailure("private authentication detail")

    class Target:
        def __init__(self, attrs):
            self.attrs = attrs
            self.commits = 0

        def execute(self, *args):
            return self

        def fetchone(self):
            return self.attrs

        def commit(self):
            self.commits += 1

    source = {"database": "zebra", "role": "zebra", "address": "172.20.0.2"}
    identity = {
        "database": "erp_destination",
        "role": "erp_owner",
        "owner": "erp_owner",
        "address": "172.21.0.2",
    }
    for code, mutate in (
        ("destination_identity", lambda w, i, a, x: i.update(database="wrong")),
        ("distinct_server", lambda w, i, a, x: i.update(address=source["address"])),
        ("destination_privilege", lambda w, i, a, x: a.__setitem__(0, True)),
        ("destination_membership", lambda w, i, a, x: x.update(members=1)),
        ("role_present_on_source", lambda w, i, a, x: x.update(source_roles=1)),
        ("destination_nonempty", lambda w, i, a, x: x.update(objects=1)),
    ):
        w = object.__new__(t.Worker)
        w.phase = "snapshot"
        w.manifest = {"source": source}
        w.hashes = {}
        w.alive = lambda: None
        w.quiescence = lambda: None
        w.pg = FakePG()
        w.cfg = {
            "source": {"host": source["address"], "dbname": "zebra"},
            "destination": {"dbname": "erp_destination", "user": "erp_owner", "password": "secret"},
            "target_address": "172.21.0.2",
            "source_address": source["address"],
        }
        w.src = object()
        info = dict(identity)
        attrs = [False] * 5 + [True]
        extra = {"members": 0, "source_roles": 0, "objects": 0}
        mutate(w, info, attrs, extra)
        target = Target(tuple(attrs))
        w.connect = lambda which, *, target=target: target
        w.identity = lambda conn, *, info=info: info

        def count(conn, query, args=None, *, extra=extra):
            if "pg_auth_members" in query:
                return extra["members"]
            if "pg_roles WHERE rolname=%s" in query:
                return extra["source_roles"]
            return extra["objects"]

        w.one = count
        refuses(lambda *, w=w: w.target({"manifest": w.manifest, "hashes": w.hashes}), code)
        assert target.commits == 0
    with tempfile.TemporaryDirectory() as directory:
        h = object.__new__(t.Host)
        h.run_directory = Path(directory)
        h.phase = "test"
        h.host_identity = {"docker_engine": "test"}
        commands = []
        h.preflight = lambda transfer: None
        h.start_worker = lambda: None
        h.close = lambda: None

        def command(name, **kwargs):
            commands.append(name)
            return {"snapshot": "0001-0001-1"}

        h.command = command
        result = h.execute("inspect")
        assert commands == ["open_snapshot", "abort"] and result["destination_mutations"] is False
    # Exercise real start_worker command construction: create must keep stdin open.
    with tempfile.TemporaryDirectory() as directory:
        h = object.__new__(t.Host)
        h.run_directory = Path(directory)
        h.source_network = "source-network"
        h.source_address = "172.20.0.2"
        h.target_address = "172.21.0.2"
        h.disposable_qa = False
        h.log = io.BytesIO()
        h.cfg = {
            "source": {"password": "source-secret"},
            "destination": {"password": "destination-secret"},
            "destination_network": "target-network",
        }
        commands = []
        attached = []

        def docker(args):
            commands.append(args)
            return b"c" * 64 if args[:2] == ["docker", "create"] else b""

        h.run = docker
        original_popen = host_module.subprocess.Popen

        def popen(args, **kwargs):
            attached.append((args, kwargs))
            return object()

        host_module.subprocess.Popen = popen
        try:
            h.start_worker()
        finally:
            host_module.subprocess.Popen = original_popen
        create = commands[0]
        assert create[:3] == ["docker", "create", "--interactive"]
        assert (
            create[create.index("--entrypoint") + 1] == "/app/.venv/bin/python"
            and t.API_IMAGE in create
        )
        assert commands[1] == ["docker", "network", "connect", "target-network", "c" * 64]
        assert attached[0][0] == ["docker", "start", "--attach", "--interactive", "c" * 64]
        assert "source-secret" not in " ".join(create) and "destination-secret" not in " ".join(
            create
        )
        assert (
            t.secure_read(h.run_directory / "worker.json")
            and (h.run_directory / "worker.py").exists()
        )
        bundle = (h.run_directory / "worker.py").read_bytes()
        assert bundle == worker_bundle() == worker_bundle()
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            assert archive.namelist() == [*WORKER_MODULES, "__main__.py"]
            assert archive.read("__main__.py") == WORKER_MAIN
            for name in WORKER_MODULES:
                assert archive.read(name) == (Path(__file__).parents[1] / name).read_bytes()
            assert all(entry.date_time == (1980, 1, 1, 0, 0, 0) for entry in archive.infolist())
        assert create[-3:] == ["/transfer/worker.py", "worker", "/transfer/worker.json"]
        # A fresh interpreter proves the archive imports without neighboring host files.
        launch = """import io, runpy, sys, types
psycopg = types.ModuleType("psycopg")
psycopg.sql = object()
sys.modules["psycopg"] = psycopg
sys.argv = sys.argv[1:]
sys.stdin = io.StringIO('{"command":"abort"}\\n')
runpy.run_path(sys.argv[0], run_name="__main__")
"""
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                launch,
                str(h.run_directory / "worker.py"),
                "worker",
                str(h.run_directory / "worker.json"),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert json.loads(result.stdout) == {
            "ok": True,
            "result": {"status": "closed", "durable_phases": [], "consumers_released": False},
        }

    # A COPY failure never commits partial data or claims activation.
    class Destination:
        def __init__(self):
            self.commits = self.rollbacks = 0

        def commit(self):
            self.commits += 1

        def rollback(self):
            self.rollbacks += 1

    worker.phase = "pre_restored"
    worker.sql = None
    worker.durable = ["pre_data"]
    worker.dst = Destination()
    worker.alive = lambda: None

    def fail(table):
        raise RuntimeError("row data and password must stay private")

    worker.copy_table = fail
    try:
        worker.copy_rows()
    except RuntimeError:
        pass
    else:
        raise AssertionError("COPY failure swallowed")
    assert worker.dst.commits == 0 and worker.dst.rollbacks == 1 and worker.durable == ["pre_data"]
    # Worker protocol discards raw exception text while retaining phase/SQLSTATE.
    original = worker_entry.Worker

    class FailedWorker:
        phase = "pre_restored"
        durable = ["pre_data"]

        def __init__(self, cfg):
            pass

        def copy_rows(self):
            error = RuntimeError("postgresql://secret:user@host/ row=private")
            error.sqlstate = "23505"
            raise error

        def abort(self):
            pass

    with tempfile.TemporaryDirectory() as directory:
        Path(directory).chmod(0o700)
        cfg = Path(directory) / "config"
        t.secure_write(cfg, b"{}")
        oldin = sys.stdin
        out = io.StringIO()
        sys.stdin = io.StringIO('{"command":"copy_rows"}\n')
        worker_entry.Worker = FailedWorker
        try:
            with contextlib.redirect_stdout(out):
                t.worker_main(str(cfg))
        finally:
            sys.stdin = oldin
            worker_entry.Worker = original
        response = json.loads(out.getvalue())
        assert (
            response["sqlstate"] == "23505"
            and response["reason"] == "worker_failure"
            and "secret" not in out.getvalue()
            and "private" not in out.getvalue()
        )
        cfg.chmod(0o644)
        refuses(lambda: t.secure_read(cfg), "protected_file_mode")
    with tempfile.TemporaryDirectory() as directory:
        h = object.__new__(t.Host)
        h.run_directory = Path(directory)
        h.process = None
        h.container = "temporary-only"
        h.log = io.BytesIO()
        secret = h.run_directory / "worker.json"
        t.secure_write(secret, b"private")

        def cleanup_failure(args):
            raise t.Refusal("native_command_failed")

        h.run = cleanup_failure
        refuses(h.close, "maintenance_cleanup_incomplete")
        assert h.cleanup_report["maintenance_container_absent"] is False
        assert not secret.exists() and h.log.closed
    with tempfile.TemporaryDirectory() as directory:
        h = object.__new__(t.Host)
        h.run_directory = Path(directory)
        h.process = None
        h.container = "temporary-only"
        h.log = io.BytesIO()
        h.phase = "copy_rows"
        secret = h.run_directory / "worker.json"
        t.secure_write(secret, b"private")
        h.preflight = lambda transfer: None

        def primary_failure():
            raise t.Refusal("original_transfer_failure")

        h.start_worker = primary_failure
        h.run = cleanup_failure
        refuses(lambda: h.execute("inspect"), "original_transfer_failure")
        assert not secret.exists() and h.cleanup_report["maintenance_container_absent"] is False
        assert (h.run_directory / "INCOMPLETE.json").exists() and (
            h.run_directory / "CLEANUP_INCOMPLETE.json"
        ).exists()

    class FailedProcess:
        class Input:
            def close(self):
                raise OSError("private detail")

        stdin = Input()

        def poll(self):
            return None

        def terminate(self):
            raise OSError("private detail")

    with tempfile.TemporaryDirectory() as directory:
        h = object.__new__(t.Host)
        h.run_directory = Path(directory)
        h.process = FailedProcess()
        h.container = "temporary-only"
        h.log = io.BytesIO()
        secret = h.run_directory / "worker.json"
        t.secure_write(secret, b"private")
        removed = []
        h.run = lambda args: removed.append(args)
        refuses(h.close, "maintenance_cleanup_incomplete")
        assert (
            removed
            and not secret.exists()
            and h.cleanup_report["maintenance_container_absent"] is True
        )
        assert h.cleanup_report["errors"] == ["attach_process_termination_failed"]

    class AbortConnection:
        def __init__(self, fail=False):
            self.closed = False
            self.fail = fail

        def rollback(self):
            if self.fail:
                raise RuntimeError("private network detail")

        def close(self):
            self.closed = True

    w = object.__new__(t.Worker)
    first = AbortConnection(True)
    second = AbortConnection()
    w.dst = first
    w.src = second
    w.durable = []
    refuses(w.abort, "abort_connection_failure")
    assert first.closed and second.closed and w.dst is w.src is None
    gate = {
        "version": 1,
        "reviewed_by_operator": "reviewer",
        "site": "erpnext.zebra.local",
        "observed_at": datetime.now(UTC).isoformat(),
        "guard_source_commit": "a" * 40,
        "admission_probe": {
            "http_status": 417,
            "cloud_mutations": 0,
            "evidence_ref": "protected/probe.json",
            "response_sha256": "b" * 64,
        },
        "conversation_lock_drain": {
            "outstanding": 0,
            "checked": 9,
            "evidence_ref": "protected/drain.json",
        },
        "producer_inventory": [
            {
                "identity": "exact-container-id",
                "kind": "worker",
                "state": "stopped",
                "evidence_ref": "protected/docker.json",
            }
        ],
        "unresolved": [],
    }
    assert "attestation" in t.validate_gate(gate)["assurance"]
    gate["unresolved"] = ["unknown consumer"]
    refuses(lambda: t.validate_gate(gate), "operator_gate_unresolved")
    try:
        from psycopg import sql
    except ImportError:
        print("PASS stdlib assertions; psycopg SQL/roundtrip checks require pinned API image")
    else:
        actual = t.canonical_migrations()
        assert len(actual) == 104 and actual[-1][:2] == (105, "scoped_plugin_installations")
        t.validate_ledger(actual)
        for field, value in ((0, 104), (1, "changed_native_name"), (2, "b" * 64)):
            altered = [list(r) for r in actual]
            altered[0][field] = value
            refuses(
                lambda *, altered=altered: t.validate_ledger(altered),
                ("source_ledger_not_canonical105"),
            )
        worker = object.__new__(t.Worker)
        worker.sql = sql
        table = {
            "name": "agent_tasks",
            "columns": [
                {"name": "deployment_namespace", "generated": ""},
                {"name": "id", "generated": ""},
                {"name": 'odd"col', "generated": ""},
                {"name": "computed", "generated": "s"},
            ],
            "pk": ["id"],
        }
        query, params = worker.query(table, False)
        rendered = query.as_string()
        assert (
            '"odd""col"' in rendered
            and "computed" not in rendered
            and "erpnext" not in rendered
            and params == [list(t.NAMESPACES)]
        )
        definition = {
            "name": "agent_definition_records",
            "columns": [{"name": "namespace_id"}, {"name": "authority_issuer"}],
        }
        pred, params = worker.predicate(definition)
        assert (
            pred.as_string().count("%s") == 2
            and params == list(t.DEFINITION)
            and "https://" not in pred.as_string()
        )
        print("PASS stdlib and real psycopg identifier/value assertions")
