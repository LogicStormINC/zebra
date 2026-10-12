"""Native sealed membership, exact settlement, tamper fallback and qualification."""
# ruff: noqa: F811

from hashlib import sha256
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.coverage_contracts import coverage_digest
from agent_core.domain.coverage_validation import expected_units
from agent_integrations.coverage_model_derivation import derive_semantic_observation
from agent_storage.postgres.coverage_membership import (
    FIELDS,
    key_chain,
    membership_records,
    membership_state,
    record_chain,
)
from agent_storage.postgres.coverage_membership_migration import COVERAGE_MEMBERSHIP_MIGRATION
from agent_storage.postgres.coverage_model_acceptance import verify_model_results
from psycopg.types.json import Jsonb

from tests.worker.coverage_model_cloud_fixtures import (  # noqa: F401
    NAMESPACE,
    dsn,
    model_cloud,
    postgres_dsn,
)
from tests.worker.test_coverage_model_acceptance import (
    accepted,
    certify,
    history,
    report_for,
    request_for,
    settled,
)


@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
def test_exact_seal_settlement_and_scoped_fast_path(model_cloud, monkeypatch):
    env = model_cloud
    with env.database.connect() as connection:
        initial = membership_state(connection, NAMESPACE, env.binding)
        keys = expected_units(env.binding.contract, (env.record,))
        assert initial is not None
        assert initial["expected_count"] == initial["seeded"] == len(keys) == 2
        assert initial["expected_digest"] == coverage_digest(
            [key.model_dump(mode="json") for key in keys]
        )
        assert initial["remaining_parts"] == initial["part_count"] == 1
        assert initial["records_seeded"] == initial["record_count"] == 1
        assert membership_records(
            connection,
            NAMESPACE,
            env.binding,
            {env.record.record_id},
        ) == (env.record,)
        assert initial["records_chain"] == record_chain(
            sha256(b"coverage-membership-records/1").hexdigest(),
            env.record,
        )
        assert membership_state(connection, "foreign", env.binding) is None
        # Native/Python chain parity preserves real strings, not stripped JSON.
        seed = sha256(b"coverage-membership/1").hexdigest()
        for name in ("space inside", '中文🙂"quote"\\slash', "line\n\tend"):
            key = env.key.model_copy(update={"record_id": name})
            row = connection.execute(
                "SELECT encode(sha256(convert_to(%s || jsonb_build_array("
                + ",".join(["%s::text"] * len(FIELDS))
                + ")::text,'UTF8')),'hex') AS digest",
                (seed, *(getattr(key, field) for field in FIELDS)),
            ).fetchone()
            assert row["digest"] == key_chain(seed, key)
    observation, _ = settled(env)
    request = request_for(env, observation)
    import agent_storage.postgres.coverage_membership as membership

    visited = []
    original = membership.membership_state

    def qualified(*args):
        result = original(*args)
        visited.append(result)
        return result

    monkeypatch.setattr(membership, "membership_state", qualified)
    import agent_storage.postgres.coverage_model_verification as verification

    monkeypatch.setattr(
        verification,
        "read_manifest",
        lambda *_: pytest.fail("qualified normal commit parsed full original manifest"),
    )
    with env.database.connect() as connection:
        state = original(connection, NAMESPACE, env.binding)
        assert state["remaining_parts"] == 0
        facts = []

        class ExactDelta:
            def execute(self, sql, args=None):
                assert "unnest(%s::jsonb[])" not in sql  # No all-key SQL upload.
                return connection.execute(sql, args)

            def __getattr__(self, name):
                return getattr(connection, name)

        verify_model_results(
            ExactDelta(),
            NAMESPACE,
            env.binding,
            request.results,
            artifacts=env.cloud,
            derive=derive_semantic_observation,
            deadlines=[],
            request=request,
            incremental_commit=True,
            verified_commits=facts,
        )
        assert visited and all(row is not None for row in visited)
        assert facts[0].expected_count == 2 and not facts[0].model_work_remaining
        assert facts[0].verifier_contract is not None
        assert original(connection, NAMESPACE, env.binding)["remaining_parts"] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE coverage_units SET ordinal=ordinal+10",
        'UPDATE coverage_units SET record=record || \'{"content_digest":"tampered"}\'::jsonb '
        "WHERE record IS NOT NULL",
        'UPDATE coverage_runs SET binding=binding || \'{"namespace":"foreign"}\'::jsonb',
        "UPDATE session_events SET payload=payload || '{\"expected_count\":0}'::jsonb "
        "WHERE event_type='coverage_manifest_committed'",
        "UPDATE session_events SET created_at=created_at+interval '1 microsecond' "
        "WHERE event_type='coverage_manifest_committed'",
        "UPDATE coverage_model_calls SET receipt_sequence=receipt_sequence+1",
    ],
)
def test_unsupported_mutation_invalidates_and_rollback_restores(model_cloud, mutation):
    env = model_cloud
    settled(env)
    with env.database.connect() as connection:
        before = membership_state(connection, NAMESPACE, env.binding)
        assert before is not None
        if mutation.startswith("UPDATE session_events"):
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="immutable"):
                with connection.transaction():
                    connection.execute(mutation)
            assert membership_state(connection, NAMESPACE, env.binding) == before
            return  # Denied at the original source; no invalidation is necessary.
        with pytest.raises(RuntimeError, match="probe"), connection.transaction():
            connection.execute(mutation)
            assert membership_state(connection, NAMESPACE, env.binding) is None
            # Restoring a mutable projection does not reset the invalidation.
            if "SET ordinal" in mutation:
                connection.execute("UPDATE coverage_units SET ordinal=ordinal-10")
                assert membership_state(connection, NAMESPACE, env.binding) is None
            raise RuntimeError("probe")
        assert membership_state(connection, NAMESPACE, env.binding) == before


@pytest.mark.parametrize(
    "table",
    [
        "coverage_membership_seals",
        "coverage_membership_parts",
        "coverage_membership_records",
    ],
)
def test_membership_root_is_not_caller_mutable(model_cloud, table):
    env = model_cloud
    with env.database.connect() as connection:
        for statement in (
            f"DELETE FROM {table}",
            f"TRUNCATE {table}",
            f"UPDATE {table} SET namespace=%s",
        ):
            with pytest.raises(psycopg.errors.RaiseException, match="database maintained"):
                with connection.transaction():
                    connection.execute(statement, ("foreign",) if "%s" in statement else None)
        assert membership_state(connection, NAMESPACE, env.binding) is not None


def test_changed_manifest_cannot_requalify_from_projection(model_cloud):
    env = model_cloud
    with env.database.connect() as connection:
        before = membership_state(connection, NAMESPACE, env.binding)
        with pytest.raises(RuntimeError, match="probe"), connection.transaction():
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="immutable"):
                with connection.transaction():
                    connection.execute(
                        "UPDATE session_events SET payload=payload-'membership' "
                        "WHERE event_type='coverage_manifest_committed'"
                    )
            assert membership_state(connection, NAMESPACE, env.binding) == before
            # A conflicting inserted manifest cannot qualify or be repaired by
            # changing the mutable projection, even with source guards enabled.
            connection.execute(
                """INSERT INTO session_events
                   (deployment_namespace,event_id,session_id,sequence,event_type,payload,
                    actor,created_at)
                   SELECT deployment_namespace,%s,session_id,
                     (SELECT max(sequence)+1 FROM session_events WHERE deployment_namespace=%s
                       AND session_id=%s),event_type,payload-'membership',actor,created_at
                   FROM session_events WHERE deployment_namespace=%s AND session_id=%s
                     AND event_type='coverage_manifest_committed'""",
                (uuid4(), NAMESPACE, env.session, NAMESPACE, env.session),
            )
            assert membership_state(connection, NAMESPACE, env.binding) is None
            connection.execute(
                "UPDATE coverage_units SET result=%s WHERE unit_key->>'kind'='part'",
                (Jsonb({}),),
            )
            assert membership_state(connection, NAMESPACE, env.binding) is None
            raise RuntimeError("probe")
        assert membership_state(connection, NAMESPACE, env.binding) == before


def test_existing_history_is_not_backfilled_by_migration(model_cloud):
    env = model_cloud
    with env.database.connect() as connection:
        before = membership_state(connection, NAMESPACE, env.binding)
        assert before is not None
        with pytest.raises(RuntimeError, match="probe"), connection.transaction():
            # Administrative migration replay ONLY in this test-owned schema.
            connection.execute("DROP TABLE coverage_membership_seals CASCADE")
            connection.execute("DROP TABLE coverage_membership_parts CASCADE")
            connection.execute("DROP TABLE coverage_membership_records CASCADE")
            connection.execute("DROP FUNCTION guard_coverage_membership() CASCADE")
            connection.execute("DROP FUNCTION advance_coverage_membership() CASCADE")
            connection.execute("ALTER TABLE coverage_units DROP COLUMN record")
            for statement in COVERAGE_MEMBERSHIP_MIGRATION.statements:
                connection.execute(statement)
            assert membership_state(connection, NAMESPACE, env.binding) is None
            assert connection.execute("SELECT 1 FROM coverage_units LIMIT 1").fetchone()
            raise RuntimeError("probe")
        assert membership_state(connection, NAMESPACE, env.binding) == before


def test_duplicate_part_call_cannot_consume_membership_twice(model_cloud):
    env = model_cloud
    settled(env)
    with env.database.connect() as connection:
        before = membership_state(connection, NAMESPACE, env.binding)
        assert before is not None and before["remaining_parts"] == 0
        with pytest.raises(RuntimeError, match="probe"), connection.transaction():
            connection.execute(
                """INSERT INTO coverage_model_calls SELECT deployment_namespace,namespace,run_id,
                   reservation_key||'-duplicate',reservation,reserved_sequence,receipt,
                   receipt_sequence FROM coverage_model_calls"""
            )
            assert membership_state(connection, NAMESPACE, env.binding) is None
            assert (
                connection.execute(
                    "SELECT remaining_parts FROM coverage_membership_seals"
                ).fetchone()["remaining_parts"]
                == 0
            )
            raise RuntimeError("probe")
        assert membership_state(connection, NAMESPACE, env.binding) == before


def test_membership_requires_exact_migration_checksum(model_cloud):
    env = model_cloud
    with env.database.connect() as connection:
        assert membership_state(connection, NAMESPACE, env.binding) is not None
        with pytest.raises(RuntimeError, match="probe"), connection.transaction():
            connection.execute("DELETE FROM zebra_schema_migrations WHERE version=93")
            assert membership_state(connection, NAMESPACE, env.binding) is None
            raise RuntimeError("probe")


@pytest.mark.parametrize("model_cloud", [{"validation_mode": "final_certification"}], indirect=True)
def test_incremental_seal_never_bypasses_final_original_manifest_proof(model_cloud):
    env = model_cloud
    request, observation, merge, _ = accepted(env)
    ref, digest = report_for(env, (observation, merge))
    objects = [
        value
        for value in env.client.objects.values()
        if sha256(value["Body"]).hexdigest() == env.binding.manifest_artifact_digest
    ]
    assert len(objects) == 1
    objects[0]["Body"] = b"corrupt original manifest after sealed incremental acceptance"
    before = history(env)
    # Incremental retries can use the sealed exact metadata. The user-approved
    # deferral must not be inherited by independent final certification.
    env.store.commit(request, fence=env.fence)
    with env.database.connect() as connection:
        assert membership_state(connection, NAMESPACE, env.binding) is not None
    with pytest.raises((ValueError, RuntimeError)):
        certify(env, ref, digest)
    assert history(env) == before
