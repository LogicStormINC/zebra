"""Pinned-image database transactions for offline namespace transfer."""

import hashlib

from transfer_inventory import (
    CATALOG_SQL,
    DEFINITION,
    IDENTITY_SQL,
    NAMESPACES,
    SESSION_SETTINGS,
    SOURCE_DATABASE,
    SOURCE_ROLE,
    TABLES,
)
from transfer_protocol import (
    Refusal,
    classify,
    digest,
    next_sequence,
    require,
    validate_catalog,
    validate_ledger,
)


class Worker:
    def __init__(self, cfg):
        import psycopg
        from psycopg import sql

        self.pg, self.sql, self.cfg = psycopg, sql, cfg
        self.src = self.dst = None
        self.phase = "new"
        self.durable = []

    def connect(self, which):
        conn = self.pg.connect(**self.cfg[which], connect_timeout=10)
        conn.execute(SESSION_SETTINGS)
        conn.commit()
        return conn

    def one(self, conn, statement, args=None):
        return conn.execute(statement, args).fetchone()[0]

    def predicate(self, table, alias=None):
        s = self.sql
        prefix = s.Identifier(alias) + s.SQL(".") if alias else s.SQL("")
        scope = classify(table)
        if scope == "ledger":
            return s.SQL("TRUE"), []
        if scope == "definition":
            return s.SQL("{}{}=%s AND {}{}=%s").format(
                prefix, s.Identifier("namespace_id"), prefix, s.Identifier("authority_issuer")
            ), list(DEFINITION)
        return s.SQL("{}{} = ANY(%s)").format(prefix, s.Identifier("deployment_namespace")), [
            list(NAMESPACES)
        ]

    def query(self, table, include_generated=True):
        s = self.sql
        columns = [
            s.Identifier(c["name"])
            for c in table["columns"]
            if include_generated or not c["generated"]
        ]
        predicate, params = self.predicate(table)
        return s.SQL("SELECT {} FROM {} WHERE {} ORDER BY {}").format(
            s.SQL(",").join(columns),
            s.Identifier("public", table["name"]),
            predicate,
            s.SQL(",").join(map(s.Identifier, table["pk"])),
        ), params

    def row_hash(self, conn, table):
        s = self.sql
        query, params = self.query(table)
        sha = hashlib.sha256()
        with conn.cursor().copy(
            s.SQL("COPY ({}) TO STDOUT WITH (FORMAT text)").format(query), params
        ) as stream:
            for block in stream:
                sha.update(block)
        pred, params = self.predicate(table)
        count = self.one(
            conn,
            s.SQL("SELECT count(*) FROM {} WHERE {}").format(
                s.Identifier("public", table["name"]), pred
            ),
            params,
        )
        return {"count": count, "sha256": sha.hexdigest()}

    def catalog(self, conn):
        result = self.one(conn, CATALOG_SQL)
        validate_catalog(result)
        return result

    def scopes(self, conn, catalog):
        s = self.sql
        result = {}
        seen = set()
        for table in catalog["tables"]:
            kind = classify(table)
            if kind == "ledger":
                continue
            predicate, params = self.predicate(table)
            if kind == "definition":
                bad = self.one(
                    conn,
                    s.SQL(
                        "SELECT count(*) FROM {} WHERE namespace_id=%s AND authority_issuer<>%s"
                    ).format(s.Identifier("public", table["name"])),
                    list(DEFINITION),
                )
                require(bad == 0, "ambiguous_erp_definition")
                cols = s.SQL("namespace_id,authority_issuer")
            else:
                cols = s.Identifier("deployment_namespace")
            values = conn.execute(
                s.SQL("SELECT DISTINCT {} FROM {} WHERE {} ORDER BY {}").format(
                    cols, s.Identifier("public", table["name"]), predicate, cols
                ),
                params,
            ).fetchall()
            result[table["name"]] = [list(v) for v in values]
            if kind == "deployment":
                seen.update(v[0] for v in values)
        require("erpnext" in seen and seen <= set(NAMESPACES), "namespace_inventory")
        return result

    def closure(self, catalog):
        s = self.sql
        rows = self.src.execute(
            "SELECT c.conrelid::regclass::text,c.confrelid::regclass::text,\n "
            "         ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDIN"
            "ALITY k(n,o) JOIN pg_attribute a ON a.attrelid=c.conrelid AND a."
            "attnum=k.n ORDER BY k.o),\n          ARRAY(SELECT a.attname FROM "
            "unnest(c.confkey) WITH ORDINALITY k(n,o) JOIN pg_attribute a ON "
            "a.attrelid=c.confrelid AND a.attnum=k.n ORDER BY k.o)\n          "
            "FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace"
            " WHERE n.nspname='public' AND c.contype='f'"
        ).fetchall()
        tables = {t["name"]: t for t in catalog["tables"]}
        for child, parent, child_cols, parent_cols in rows:
            require(child in tables and parent in tables, "external_fk")
            cp, ca = self.predicate(tables[child], "c")
            pp, pa = self.predicate(tables[parent], "p")
            join = s.SQL(" AND ").join(
                s.SQL("c.{}=p.{}").format(s.Identifier(a), s.Identifier(b))
                for a, b in zip(child_cols, parent_cols, strict=False)
            )
            nonnull = s.SQL(" AND ").join(
                s.SQL("c.{} IS NOT NULL").format(s.Identifier(a)) for a in child_cols
            )
            query = s.SQL(
                "SELECT EXISTS(SELECT 1 FROM {} c WHERE ({}) AND ({}) AND NOT EXI"
                "STS(SELECT 1 FROM {} p WHERE ({}) AND ({})))"
            ).format(
                s.Identifier("public", child), cp, nonnull, s.Identifier("public", parent), join, pp
            )
            require(not self.one(self.src, query, ca + pa), "selected_fk_not_closed")

    def identity(self, conn):
        info = self.one(conn, IDENTITY_SQL)
        require(
            info["version"] == "170005"
            and info["encoding"] == "UTF8"
            and info["collate"] == info["ctype"] == "en_US.utf8"
            and info["provider"] == "c"
            and info["collversion"] == info["actual_collversion"],
            "database_version_locale",
        )
        require(info["address"] is not None and info["port"] == 5432, "connection_address")
        return info

    def open_snapshot(self):
        require(self.phase == "new", "phase_order")
        self.src = self.connect("source")
        self.src.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        self.src.execute(
            self.sql.SQL("LOCK TABLE {} IN ACCESS SHARE MODE").format(
                self.sql.SQL(",").join(self.sql.Identifier("public", n) for n in TABLES)
            )
        )
        info = self.identity(self.src)
        expected = (
            self.cfg["source"]
            if self.cfg.get("disposable_qa")
            else {"dbname": SOURCE_DATABASE, "user": SOURCE_ROLE}
        )
        require(
            info["database"] == expected["dbname"] and info["role"] == expected["user"],
            "source_identity",
        )
        catalog = self.catalog(self.src)
        self.closure(catalog)
        rows = self.src.execute(
            "SELECT version,name,checksum FROM public.zebra_schema_migrations ORDER BY version"
        ).fetchall()
        validate_ledger(rows)
        self.manifest = {
            "catalog": catalog,
            "migrations": [list(r) for r in rows],
            "source": info,
            "scopes": self.scopes(self.src, catalog),
        }
        self.hashes = {t["name"]: self.row_hash(self.src, t) for t in catalog["tables"]}
        self.snapshot = self.one(self.src, "SELECT pg_export_snapshot()")
        self.phase = "snapshot"
        return {
            "snapshot": self.snapshot,
            "manifest": self.manifest,
            "hashes": self.hashes,
            "fingerprint": digest(self.manifest),
        }

    def alive(self):
        require(
            self.src is not None
            and self.one(self.src, "SELECT current_setting('transaction_read_only')") == "on",
            "snapshot_lost",
        )
        require(self.catalog(self.src) == self.manifest["catalog"], "catalog_drift")

    def quiescence(self):
        # A fresh read-only snapshot detects writes hidden from the exported snapshot.
        conn = self.connect("source")
        try:
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            s = self.sql
            tables = {t["name"]: t for t in self.manifest["catalog"]["tables"]}
            for name in (
                "session_command_pending",
                "broker_command_inbox",
                "broker_control_inbox",
                "broker_outbox",
                "command_shadow_outbox",
                "task_schedules",
                "task_schedule_firings",
            ):
                require(self.row_hash(conn, tables[name])["count"] == 0, "nonempty_execution_queue")
            predicate, params = self.predicate(tables["worker_leases"])
            require(
                self.one(
                    conn,
                    s.SQL(
                        "SELECT count(*) FROM public.worker_leases WHERE ({}) AND release"
                        "d_at IS NULL"
                    ).format(predicate),
                    params,
                )
                == 0,
                "unreleased_worker_lease",
            )
            for name, allowed in (
                ("effect_outbox", ["succeeded"]),
                ("handoff_dispatch_outbox", ["acked"]),
            ):
                predicate, params = self.predicate(tables[name])
                require(
                    self.one(
                        conn,
                        s.SQL(
                            "SELECT count(*) FROM {} WHERE ({}) AND NOT (status = ANY(%s))"
                        ).format(s.Identifier("public", name), predicate),
                        params + [allowed],
                    )
                    == 0,
                    "inflight_dispatch_outbox",
                )
            current = {t["name"]: self.row_hash(conn, t) for t in tables.values()}
            require(current == self.hashes, "source_rows_changed_after_snapshot")
        finally:
            conn.rollback()
            conn.close()

    def target(self, approved):
        require(self.phase == "snapshot", "phase_order")
        require(
            self.manifest == approved["manifest"] and self.hashes == approved["hashes"],
            "approval_drift",
        )
        self.alive()
        self.quiescence()
        cfg = self.cfg
        self.dst = self.connect("destination")
        info = self.identity(self.dst)
        require(
            info["database"] == cfg["destination"]["dbname"]
            and info["role"] == info["owner"] == cfg["destination"]["user"]
            and info["database"] != self.manifest["source"]["database"]
            and info["role"] != self.manifest["source"]["role"],
            "destination_identity",
        )
        require(
            info["address"] == cfg["target_address"]
            and info["address"] != self.manifest["source"]["address"]
            and self.manifest["source"]["address"] == cfg["source_address"],
            "distinct_server",
        )
        attrs = self.dst.execute(
            "SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypa"
            "ssrls,rolcanlogin FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        require(attrs == (False, False, False, False, False, True), "destination_privilege")
        require(
            self.one(
                self.dst,
                (
                    "SELECT count(*) FROM pg_auth_members WHERE member=(SELECT oid FR"
                    "OM pg_roles WHERE rolname=current_user)"
                ),
            )
            == 0,
            "destination_membership",
        )
        require(
            self.one(self.src, "SELECT count(*) FROM pg_roles WHERE rolname=%s", [info["role"]])
            == 0,
            "role_present_on_source",
        )
        # Attempt with exact destination credentials at the actual original endpoint.
        probe = dict(cfg["destination"])
        for key in ("host", "hostaddr", "port", "dbname"):
            probe.pop(key, None)
            if key in cfg["source"]:
                probe[key] = cfg["source"][key]
        try:
            conn = self.pg.connect(**probe, connect_timeout=5)
        except self.pg.OperationalError as error:
            require(
                error.sqlstate in ("28P01", "28000")
                or "password authentication failed" in str(error)
                or "role" in str(error)
                and "does not exist" in str(error),
                "source_authentication_not_proven",
            )
        else:
            conn.close()
            raise Refusal("destination_credentials_work_on_source")
        objects = self.one(
            self.dst,
            (
                "SELECT (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n"
                ".oid=c.relnamespace WHERE n.nspname NOT IN ('pg_catalog','inform"
                "ation_schema') AND n.nspname NOT LIKE 'pg_toast%' AND n.nspname "
                "NOT LIKE 'pg_temp%') + (SELECT count(*) FROM pg_proc p JOIN pg_n"
                "amespace n ON n.oid=p.pronamespace WHERE n.nspname NOT IN ('pg_c"
                "atalog','information_schema')) + (SELECT count(*) FROM pg_namesp"
                "ace WHERE nspname NOT IN ('public','pg_catalog','information_sch"
                "ema') AND nspname NOT LIKE 'pg_toast%' AND nspname NOT LIKE 'pg_"
                "temp%') + (SELECT count(*) FROM pg_extension WHERE extname<>'plp"
                "gsql') + (SELECT count(*) FROM pg_type t JOIN pg_namespace n ON "
                "n.oid=t.typnamespace WHERE n.nspname='public' AND t.typtype<>'c'"
                " AND t.typelem=0)"
            ),
        )
        require(objects == 0, "destination_nonempty")
        self.dst.commit()
        self.phase = "target_checked"
        return {"target_checked": True}

    def pre_restored(self):
        require(self.phase == "target_checked", "phase_order")
        self.alive()
        self.durable.append("pre_data")
        self.phase = "pre_restored"
        return {"phase": self.phase}

    def copy_table(self, table):
        s = self.sql
        query, params = self.query(table, False)
        cols = s.SQL(",").join(
            s.Identifier(c["name"]) for c in table["columns"] if not c["generated"]
        )
        with self.src.cursor().copy(
            s.SQL("COPY ({}) TO STDOUT WITH (FORMAT text)").format(query), params
        ) as source:
            with self.dst.cursor().copy(
                s.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT text)").format(
                    s.Identifier("public", table["name"]), cols
                )
            ) as target:
                for block in source:
                    target.write(block)

    def copy_rows(self):
        require(self.phase == "pre_restored", "phase_order")
        self.alive()
        try:
            for table in self.manifest["catalog"]["tables"]:
                self.copy_table(table)
            self.dst.commit()
        except BaseException:
            self.dst.rollback()
            raise
        self.durable.append("data")
        self.phase = "copied"
        return {"phase": self.phase, "tables": len(TABLES)}

    def verify(self):
        require(self.phase == "copied", "phase_order")
        self.alive()
        self.durable.append("post_data")
        require(self.catalog(self.dst) == self.manifest["catalog"], "restored_catalog_mismatch")
        s = self.sql
        sequences = []
        for seq in self.manifest["catalog"]["sequences"]:
            maximum = self.one(
                self.dst,
                s.SQL("SELECT max({}) FROM {}").format(
                    s.Identifier(seq["column"]), s.Identifier("public", seq["table"])
                ),
            )
            value, called = next_sequence(seq, maximum)
            self.one(
                self.dst,
                "SELECT setval(%s::regclass,%s,%s)",
                ["public." + s.Identifier(seq["name"]).as_string(self.dst), value, called],
            )
            actual = self.dst.execute(
                s.SQL("SELECT last_value,is_called FROM {}").format(
                    s.Identifier("public", seq["name"])
                )
            ).fetchone()
            require(actual == (value, called), "sequence_state")
            require(maximum is None or actual[0] + 1 > maximum, "sequence_collision")
            sequences.append({"name": seq["name"], "last_value": value, "is_called": called})
        self.dst.commit()
        self.durable.append("sequences")
        for table in self.manifest["catalog"]["tables"]:
            pred, params = self.predicate(table)
            require(
                self.one(
                    self.dst,
                    s.SQL("SELECT count(*) FROM {} WHERE NOT ({})").format(
                        s.Identifier("public", table["name"]), pred
                    ),
                    params,
                )
                == 0,
                "foreign_destination_scope",
            )
        require(
            self.scopes(self.dst, self.manifest["catalog"]) == self.manifest["scopes"],
            "scope_mismatch",
        )
        result = {t["name"]: self.row_hash(self.dst, t) for t in self.manifest["catalog"]["tables"]}
        require(result == self.hashes, "row_count_or_hash_mismatch")
        # Source snapshot remains alive through both native restores and target verification.
        self.alive()
        self.quiescence()
        self.dst.rollback()
        self.phase = "verified"
        return {
            "status": "verified_unactivated",
            "fingerprint": digest(self.manifest),
            "hashes": result,
            "sequences": sequences,
            "durable_phases": self.durable,
            "consumers_released": False,
        }

    def abort(self):
        failed = False
        for conn in (self.dst, self.src):
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    failed = True
                finally:
                    conn.close()
        self.dst = self.src = None
        require(not failed, "abort_connection_failure")
        return {"status": "closed", "durable_phases": self.durable, "consumers_released": False}
