"""Fixed-size observation fields, derived atomically from Session projection writes.

ponytail: database triggers cover every projection writer, including Handoff/import;
legacy rows need explicit bounded preparation, never repair on an observation GET.
"""

from typing import Any

SCHEMA = """CREATE TABLE IF NOT EXISTS session_observation_headers (
 deployment_namespace TEXT NOT NULL,
 session_id TEXT NOT NULL,
 title TEXT NOT NULL CHECK(length(title)<=512),
 title_truncated INTEGER NOT NULL CHECK(title_truncated IN (0,1)),
 status TEXT NOT NULL CHECK(length(status)<=32),
 current_sequence INTEGER NOT NULL CHECK(current_sequence>=0),
 clarification_id TEXT CHECK(length(clarification_id)<=256),
 clarification_invalid INTEGER NOT NULL CHECK(clarification_invalid IN (0,1)),
 PRIMARY KEY(deployment_namespace,session_id))"""

COLUMNS = (
    "deployment_namespace,session_id,title,title_truncated,status,current_sequence,"
    "clarification_id,clarification_invalid"
)
_UPDATE = ",".join(f"{name}=excluded.{name}" for name in COLUMNS.split(",")[2:])


def _values(source: str, *, postgres: bool) -> str:
    if postgres:
        identity = f"{source}.clarification_context_json->>'clarification_id'"
        valid = (
            f"jsonb_typeof({source}.clarification_context_json->'clarification_id')='string' "
            f"AND length({identity}) BETWEEN 1 AND 256 AND btrim({identity})<>'' "
            f"AND {identity} !~ '[[:cntrl:]]'"
        )
        prefix = f"{source}.deployment_namespace,{source}.session_id::text"
    else:
        identity = f"json_extract({source}.clarification_context_json,'$.clarification_id')"
        valid = (
            f"CASE WHEN json_valid({source}.clarification_context_json) THEN "
            f"json_type({source}.clarification_context_json,'$.clarification_id')='text' "
            f"AND length({identity}) BETWEEN 1 AND 256 AND trim({identity})<>'' "
            f"AND {identity} NOT GLOB ('*['||char(1)||'-'||char(31)||']*') "
            f"AND instr({identity},char(0))=0 ELSE 0 END"
        )
        prefix = f"'',{source}.session_id"
    # CASE is lazy: malformed legacy SQLite JSON is never passed to json_extract.
    present = f"{source}.clarification_context_json IS NOT NULL"
    return (
        f"{prefix},substr({source}.title,1,512),"
        f"CASE WHEN length({source}.title)>512 THEN 1 ELSE 0 END,"
        f"{source}.status,{source}.current_sequence,"
        f"CASE WHEN {present} THEN CASE WHEN {valid} THEN {identity} END END,"
        f"CASE WHEN {present} THEN CASE WHEN {valid} THEN 0 ELSE 1 END ELSE 0 END"
    )


def upsert_statement(select: str) -> str:
    return (
        f"INSERT INTO session_observation_headers ({COLUMNS}) {select} "
        f"ON CONFLICT(deployment_namespace,session_id) DO UPDATE SET {_UPDATE}"
    )


def sqlite_statements() -> tuple[str, ...]:
    upsert = upsert_statement(f"VALUES ({_values('NEW', postgres=False)})")
    return (
        SCHEMA,
        *(
            f"CREATE TRIGGER IF NOT EXISTS session_observation_header_{operation.lower()} "
            f"AFTER {operation} ON session_projections BEGIN {upsert}; END"
            for operation in ("INSERT", "UPDATE")
        ),
        "CREATE TRIGGER IF NOT EXISTS session_observation_header_delete "
        "AFTER DELETE ON session_projections BEGIN "
        "DELETE FROM session_observation_headers "
        "WHERE deployment_namespace='' AND session_id=OLD.session_id; END",
    )


def postgres_statements() -> tuple[str, ...]:
    upsert = upsert_statement(f"VALUES ({_values('NEW', postgres=True)})")
    return (
        SCHEMA.replace("current_sequence INTEGER", "current_sequence BIGINT"),
        "CREATE FUNCTION derive_session_observation_header() RETURNS trigger AS $$ BEGIN "
        + upsert
        + "; RETURN NEW; END; $$ LANGUAGE plpgsql",
        "CREATE TRIGGER session_observation_header_write AFTER INSERT OR UPDATE "
        "ON session_projections FOR EACH ROW EXECUTE FUNCTION derive_session_observation_header()",
        "CREATE FUNCTION delete_session_observation_header() RETURNS trigger AS $$ BEGIN "
        "DELETE FROM session_observation_headers "
        "WHERE deployment_namespace=OLD.deployment_namespace AND session_id=OLD.session_id::text; "
        "RETURN OLD; END; $$ LANGUAGE plpgsql",
        "CREATE TRIGGER session_observation_header_delete AFTER DELETE ON session_projections "
        "FOR EACH ROW EXECUTE FUNCTION delete_session_observation_header()",
    )


def prepare_session_observation_headers(
    connection: Any,
    *,
    deployment_namespace: str = "",
    after_session_id: str = "",
    limit: int = 256,
    postgres: bool = False,
) -> tuple[str, ...]:
    """Explicit one-page maintenance; caller owns the transaction and I/O deadline."""
    if type(limit) is not int or not 1 <= limit <= 256:
        raise ValueError("observation header preparation requires a bounded page")
    if not postgres and deployment_namespace:
        raise ValueError("SQLite observation headers use the local namespace")
    marker = "%s" if postgres else "?"
    namespace = f"p.deployment_namespace={marker} AND " if postgres else ""
    seek = (
        f"p.session_id>{marker}::uuid AND "
        if postgres and after_session_id
        else f"p.session_id>{marker} AND "
        if not postgres
        else ""
    )
    select = (
        f"SELECT {_values('p', postgres=postgres)} FROM session_projections p "
        f"WHERE {namespace}{seek}TRUE ORDER BY p.session_id LIMIT {marker}"
    )
    parameters = (
        (deployment_namespace, *((after_session_id,) if after_session_id else ()), limit)
        if postgres
        else (after_session_id, limit)
    )
    rows = connection.execute(
        upsert_statement(select) + " RETURNING session_id", parameters
    ).fetchall()
    return tuple(sorted(str(row["session_id"]) for row in rows))
