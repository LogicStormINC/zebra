"""Runnable design counterexamples; not a PostgreSQL or AMQP integration test."""

import sqlite3


def must_conflict(db: sqlite3.Connection, sql: str, args: tuple) -> None:
    try:
        db.execute(sql, args)
    except sqlite3.IntegrityError:
        return
    raise AssertionError("Expected the duplicate constraint to reject this insert")


def main() -> None:
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE old_box(kind TEXT, aggregate_id TEXT, version INT, "
                   "UNIQUE(kind, aggregate_id, version))")
        for kind in ("session", "source"):
            values = (kind, "same-object", 1)
            db.execute("INSERT INTO old_box VALUES (?, ?, ?)", values)
            # A distinct command/window is incorrectly rejected by the old key.
            must_conflict(db, "INSERT INTO old_box VALUES (?, ?, ?)", values)

        db.execute("CREATE TABLE box(namespace TEXT, scope TEXT, kind TEXT, "
                   "operation TEXT, generation INT, message TEXT UNIQUE, "
                   "UNIQUE(namespace, scope, kind, operation, generation))")
        sql = "INSERT INTO box VALUES (?, ?, ?, ?, ?, ?)"
        first = ("dev", "alice", "command", "c1", 0, "m1")
        db.execute(sql, first)
        must_conflict(db, sql, first)  # Physical retry must reuse the row.
        must_conflict(db, sql, (*first[:5], "different-message"))
        for row in (
            ("dev", "alice", "command", "c2", 0, "m2"),
            ("dev", "alice", "command", "c1", 1, "m3"),
            ("dev", "bob", "command", "c1", 0, "m4"),
        ):
            db.execute(sql, row)
        assert db.execute("SELECT count(*) FROM box").fetchone()[0] == 4

        db.execute("CREATE TABLE inbox(namespace TEXT, role TEXT, message TEXT, "
                   "digest TEXT, UNIQUE(namespace, role, message))")
        inbox_sql = "INSERT INTO inbox VALUES (?, ?, ?, ?)"
        receipt = ("dev", "executor", "m1", "original-digest")
        db.execute(inbox_sql, receipt)
        must_conflict(db, inbox_sql, receipt)
        db.execute(inbox_sql, ("dev", "executor", "m3", "recovery-digest"))
        stored = db.execute("SELECT digest FROM inbox WHERE namespace=? "
                            "AND role=? AND message=?", receipt[:3]).fetchone()[0]
        must_conflict(db, inbox_sql, (*receipt[:3], "conflicting-digest"))
        assert stored != "conflicting-digest"  # Duplicate ID needs content validation.

        db.execute("SAVEPOINT handoff")
        db.execute(inbox_sql, ("dev", "executor", "rolled-back", "digest"))
        db.execute("ROLLBACK TO handoff")
        db.execute("RELEASE handoff")
        assert not db.execute("SELECT 1 FROM inbox WHERE message='rolled-back'").fetchall()

        db.execute("CREATE TABLE lease(owner TEXT, fence INT, expires INT, result TEXT)")
        db.execute("INSERT INTO lease VALUES ('old', 1, 10, NULL)")
        db.execute("UPDATE lease SET owner='new', fence=2, expires=30 WHERE expires<=20")
        update = ("UPDATE lease SET result='completed' WHERE owner=? "
                  "AND fence=? AND expires>?")
        assert db.execute(update, ("old", 1, 21)).rowcount == 0
        assert db.execute(update, ("new", 2, 31)).rowcount == 0
        assert db.execute(update, ("new", 2, 21)).rowcount == 1
    print("PASS: 8 design scenarios; runtime PG/Rabbit integration remains untested")


if __name__ == "__main__":
    main()
