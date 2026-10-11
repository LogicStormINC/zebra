"""Optional dedicated-PostgreSQL nested-work meter; no global statistics reset."""

import os


def snapshot(database):
    if os.environ.get("ZEBRA_COVERAGE_SERVER_SQL") != "1":
        return None
    with database.connect() as connection:
        # Benchmark-only dedicated instance, before the measured business path.
        rows = connection.execute(
            """SELECT queryid,toplevel,query,calls,total_exec_time,rows,
               shared_blks_hit,shared_blks_read,
               coalesce((to_jsonb(s)->>'shared_blk_read_time')::float8,
                 (to_jsonb(s)->>'blk_read_time')::float8,0) AS blk_read_time,
               coalesce((to_jsonb(s)->>'shared_blk_write_time')::float8,
                 (to_jsonb(s)->>'blk_write_time')::float8,0) AS blk_write_time
               FROM public.pg_stat_statements s WHERE dbid=(SELECT oid FROM pg_database
                 WHERE datname=current_database()) AND query NOT LIKE %s""",
            ("%pg_stat_statements%",),
        ).fetchall()
        stamp = connection.execute(
            "SELECT stats_reset,dealloc FROM public.pg_stat_statements_info"
        ).fetchone()
    return {(row["queryid"], row["toplevel"]): row for row in rows}, stamp


def difference(before, after):
    if before is None or after is None:
        return {"available": False, "boundary": "server monitoring not enabled"}
    previous, original_stamp = before
    current, final_stamp = after
    if original_stamp != final_stamp or previous.keys() - current.keys():
        raise AssertionError("server SQL statistics reset or evicted during measurement")
    rows = []
    counters = ("calls", "total_exec_time", "rows", "shared_blks_hit", "shared_blks_read",
                "blk_read_time", "blk_write_time")
    for key, row in current.items():
        old = previous.get(key, {})
        delta = {name: row[name] - old.get(name, 0) for name in counters}
        if any(value < 0 for value in delta.values()):
            raise AssertionError("server SQL counters decreased during measurement")
        if delta["calls"] > 0:
            rows.append({"sql": row["query"], "top_level": row["toplevel"], **delta})
    return {
        "available": True, "calls": sum(row["calls"] for row in rows),
        "top_level_calls": sum(row["calls"] for row in rows if row["top_level"]),
        "nested_calls": sum(row["calls"] for row in rows if not row["top_level"]),
        "rows": sum(row["rows"] for row in rows),
        "inclusive_exec_milliseconds": sum(row["total_exec_time"] for row in rows),
        "top_statements": sorted(rows, key=lambda row: row["calls"], reverse=True)[:30],
        "boundary": "dedicated instance; pg_stat_statements.track=all; monitoring excluded",
        "nested_times_are_not_additive": True,
    }
