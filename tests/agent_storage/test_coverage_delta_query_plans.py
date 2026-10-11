"""Native index plans with synthetic rows, not semantic or end-to-end load proof."""
# ruff: noqa: F811

import json
from uuid import UUID

import pytest
from agent_storage.postgres.coverage_proof_prefetch import MATERIALIZATION_PAGE_QUERY
from agent_storage.postgres.database import PostgresDatabase
from psycopg.types.json import Jsonb

from tests.worker.coverage_model_cloud_fixtures import dsn, postgres_dsn  # noqa: F401


@pytest.mark.parametrize("lookup", ["unit", "record"])
def test_delta_probes_use_exact_scope_indexes_without_scanning_history(dsn, lookup):
    database = PostgresDatabase(dsn, deployment_namespace="probe")
    with database.connect() as connection:
        # These intentionally incomplete synthetic rows invalidate the native
        # proof root. They exercise planner cardinality, never qualify a receipt.
        connection.execute(
            """INSERT INTO coverage_model_calls
               (deployment_namespace,namespace,run_id,reservation_key,reservation,
                 reserved_sequence,receipt,receipt_sequence)
               SELECT 'probe','tenant-'||(n/1000),'run',n::text,
                 jsonb_build_object('key',jsonb_build_object('record_id',n::text)),
                 n+1,jsonb_build_object('synthetic',true),n+2
               FROM generate_series(1,5000) n"""
        )
        connection.execute("ANALYZE coverage_model_calls")
        expected = "coverage_model_settled_unit" if lookup == "unit" else (
            "coverage_model_record_calls"
        )
        predicate = "reservation->'key'=%s AND receipt IS NOT NULL" if lookup == "unit" else (
            "reservation #>> '{key,record_id}'=%s"
        )
        value = Jsonb({"record_id": "2525"}) if lookup == "unit" else "2525"
        sql = "SELECT reservation_key FROM coverage_model_calls WHERE " + (
            "deployment_namespace=%s AND namespace=%s AND run_id=%s AND " + predicate
        )
        arguments = ("probe", "tenant-2", "run", value)
        assert connection.execute(sql, arguments).fetchone()["reservation_key"] == "2525"
        assert not connection.execute(sql, ("probe", "tenant-3", "run", value)).fetchall()
        plan = connection.execute(
            "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + sql, arguments,
        ).fetchone()["QUERY PLAN"][0]
        body = json.dumps(plan)
        assert expected in body and "Seq Scan" not in body
        assert plan["Plan"]["Actual Rows"] == 1
        assert plan["Plan"].get("Rows Removed by Filter", 0) == 0
        assert connection.execute(
            "SELECT invalidated FROM coverage_model_summary WHERE deployment_namespace=%s "
            "AND namespace=%s AND run_id=%s", arguments[:3],
        ).fetchone()["invalidated"]  # Never bless incomplete rows from counts.


@pytest.mark.parametrize("lookup", ["exact_key", "reservation"])
def test_membership_part_transition_uses_indexed_candidates(dsn, lookup):
    database = PostgresDatabase(dsn, deployment_namespace="probe")
    with database.connect() as connection:
        # Administrator-only synthetic planner data in this owned test schema.
        # No manifest/source seal exists, so these rows cannot qualify proof.
        connection.execute("ALTER TABLE coverage_membership_parts DISABLE TRIGGER USER")
        connection.execute(
            """INSERT INTO coverage_membership_parts
               (deployment_namespace,namespace,run_id,unit_digest,unit_key,reservation_key)
               SELECT 'probe','tenant-'||(n/1000),'run',n::text,
                 jsonb_build_object('record_id',n::text),n::text
               FROM generate_series(1,5000) n"""
        )
        connection.execute("ALTER TABLE coverage_membership_parts ENABLE TRIGGER USER")
        connection.execute("ANALYZE coverage_membership_parts")
        predicate = ("md5(unit_key::text)=md5(%s::jsonb::text) AND unit_key=%s"
                     if lookup == "exact_key" else "reservation_key=%s")
        args = ((Jsonb({"record_id": "2525"}),) * 2 if lookup == "exact_key" else ("2525",))
        query = ("SELECT unit_digest FROM coverage_membership_parts WHERE "
                 "deployment_namespace=%s AND namespace=%s AND run_id=%s AND " + predicate)
        plan = connection.execute(
            "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + query,
            ("probe", "tenant-2", "run", *args),
        ).fetchone()["QUERY PLAN"][0]
        serialized = json.dumps(plan)
        expected = ("coverage_membership_part_key" if lookup == "exact_key" else
                    "coverage_membership_reservation")
        assert expected in serialized and "Seq Scan" not in serialized
        assert plan["Plan"]["Actual Rows"] == 1
        assert plan["Plan"].get("Rows Removed by Filter", 0) == 0
        assert not connection.execute(
            query, ("probe", "tenant-3", "run", *args),
        ).fetchall()
        assert connection.execute("SELECT 1 FROM coverage_membership_seals").fetchone() is None


def test_materialization_page_uses_uri_and_event_identity_indexes(dsn):
    database = PostgresDatabase(dsn, deployment_namespace="probe")
    session = UUID("00000000-0000-0000-0000-000000000094")
    with database.connect() as connection:
        # Synthetic canonical-looking lookup rows have no governed lifecycle,
        # manifest or budget: index-plan evidence only, never valid proof.
        connection.execute(
            "INSERT INTO session_streams VALUES ('probe',%s,5000)", (session,),
        )
        connection.execute(
            """INSERT INTO session_events
               (deployment_namespace,event_id,session_id,sequence,event_type,payload,actor,created_at)
               SELECT 'probe',md5(n::text)::uuid,%s,n,'coverage_artifact_materialized',
                 jsonb_build_object('metadata',jsonb_build_object(
                   'artifact_uri','artifact://'||md5(n::text)::uuid::text)),
                 'system',clock_timestamp() FROM generate_series(1,5000) n""",
            (session,),
        )
        connection.execute("ANALYZE session_events")
        identifiers = [connection.execute(
            "SELECT md5(%s)::uuid AS id", (str(number),),
        ).fetchone()["id"] for number in (2525, 2526)]
        args = ("probe", identifiers[:1], [f"artifact://{key}" for key in identifiers], 5)
        plan = connection.execute(
            "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + MATERIALIZATION_PAGE_QUERY, args,
        ).fetchone()["QUERY PLAN"][0]
        serialized = json.dumps(plan)
        assert "coverage_artifact_materialized_uri" in serialized
        assert "session_events_pkey" in serialized and "Seq Scan" not in serialized
        assert plan["Plan"]["Actual Rows"] == 2
        assert not connection.execute(
            MATERIALIZATION_PAGE_QUERY, ("foreign", *args[1:]),
        ).fetchall()


def test_selected_manifest_records_use_scope_primary_key(dsn):
    database = PostgresDatabase(dsn, deployment_namespace="probe")
    with database.connect() as connection:
        # Synthetic plan rows have no sealed manifest and cannot qualify proof.
        connection.execute("ALTER TABLE coverage_membership_records DISABLE TRIGGER USER")
        connection.execute(
            """INSERT INTO coverage_membership_records
               SELECT 'probe','tenant-'||(n/1000),'run',n::text,n,
                 jsonb_build_object('synthetic',true)
               FROM generate_series(1,5000) n"""
        )
        connection.execute("ALTER TABLE coverage_membership_records ENABLE TRIGGER USER")
        connection.execute("ANALYZE coverage_membership_records")
        query = ("SELECT record FROM coverage_membership_records WHERE deployment_namespace=%s "
                 "AND namespace=%s AND run_id=%s AND record_id=ANY(%s) "
                 "ORDER BY ordinal LIMIT 1001")
        args = ("probe", "tenant-2", "run", ["2525", "2526"])
        plan = connection.execute(
            "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + query, args,
        ).fetchone()["QUERY PLAN"][0]
        serialized = json.dumps(plan)
        assert "coverage_membership_records_pkey" in serialized and "Seq Scan" not in serialized
        assert plan["Plan"]["Actual Rows"] == 2
        assert not connection.execute(query, ("probe", "tenant-3", "run", args[-1])).fetchall()
        assert connection.execute("SELECT 1 FROM coverage_membership_seals").fetchone() is None
