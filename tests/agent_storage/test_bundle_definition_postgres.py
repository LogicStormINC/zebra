"""Bundle v2 storage acceptance on a disposable PostgreSQL, including v109 upgrade."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest
from agent_core.application.agent_definition_binding import DefinitionBindingService
from agent_core.application.agent_definitions import (
    AgentDefinitionDraftService,
    PublisherGrantCeiling,
    PublisherGrantError,
    StaticPublisherGrantResolver,
)
from agent_core.application.agent_publication import (
    AgentDefinitionPublicationService,
    PublicationGateEvidence,
)
from agent_core.domain.agent_definitions import AgentDefinition, AgentDefinitionVersion
from agent_core.domain.bundle_definition import BundleDefinitionVersion, parse_definition_snapshot
from agent_core.domain.identifiers import AgentDefinitionId, AgentDefinitionVersionId
from agent_core.domain.runtime_assembly import RuntimeAssembly
from agent_storage.postgres.agent_registry import AgentRegistryStorageError, PostgresAgentRegistry
from agent_storage.postgres.migration_runner import apply_postgres_migrations
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from tests.agent_core.test_bundle_definition import (
    NOW,
    REFERENCES,
    assembly_payload,
    bundle_version,
)


@pytest.fixture(scope="module")
def raw_bundle_dsn() -> Iterator[str]:
    name = f"zebra-bundle-definition-{uuid4().hex[:12]}"
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-d",
            "--name",
            name,
            "-e",
            "POSTGRES_PASSWORD=disposable",
            "-p",
            "127.0.0.1::5432",
            "postgres:17-alpine",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        port = subprocess.check_output(
            [
                "docker",
                "inspect",
                "--format",
                '{{(index (index .NetworkSettings.Ports "5432/tcp") 0).HostPort}}',
                name,
            ],
            text=True,
        ).strip()
        dsn = f"host=127.0.0.1 port={port} dbname=postgres user=postgres password=disposable"
        until = time.monotonic() + 30
        while True:
            try:
                with psycopg.connect(dsn):
                    break
            except psycopg.OperationalError:
                if time.monotonic() >= until:
                    raise
                time.sleep(0.1)
        yield dsn
    finally:
        subprocess.run(["docker", "rm", "-f", name], check=True, capture_output=True)


@pytest.fixture
def bundle_dsn(raw_bundle_dsn: str) -> str:
    apply_postgres_migrations(raw_bundle_dsn)
    return raw_bundle_dsn


def seed(registry, version):
    registry.save_definition(
        AgentDefinition(
            definition_id=version.definition_id,
            authority_issuer=version.authority_issuer,
            namespace_id=version.namespace_id,
            name="native",
            created_at=NOW,
        )
    )
    registry.save_version(version)


def test_01_v109_upgrade_preserves_all_legacy_bytes_without_sidecar_reads(
    raw_bundle_dsn, monkeypatch
):
    import agent_storage.postgres.migration_runner as runner

    database = "upgrade_" + uuid4().hex
    with psycopg.connect(raw_bundle_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    bundle_dsn = make_conninfo(raw_bundle_dsn, dbname=database)
    migrations = runner.MIGRATIONS
    monkeypatch.setattr(runner, "MIGRATIONS", tuple(m for m in migrations if m.version <= 109))
    apply_postgres_migrations(bundle_dsn)
    registry = PostgresAgentRegistry(bundle_dsn, deployment_namespace="bundle-test")
    version = bundle_version()
    legacy = AgentDefinitionVersion.model_validate(
        version.model_dump(exclude={"runtime_assembly", "schema_version", "definition_digest"})
    )
    seed(registry, legacy)
    assert registry.get_version(legacy.scope, legacy.version_id) == legacy
    with psycopg.connect(bundle_dsn) as connection:
        assert (
            connection.execute("SELECT to_regclass('agent_definition_bundle_versions')").fetchone()[
                0
            ]
            is None
        )
        before = connection.execute(
            "SELECT row_to_json(v)::text FROM agent_definition_versions v"
        ).fetchall()
    monkeypatch.setattr(runner, "MIGRATIONS", migrations)
    apply_postgres_migrations(bundle_dsn)
    with psycopg.connect(bundle_dsn) as connection:
        assert (
            connection.execute(
                "SELECT row_to_json(v)::text FROM agent_definition_versions v"
            ).fetchall()
            == before
        )
    assert registry.get_version(legacy.scope, legacy.version_id) == legacy
    assert registry.save_version(legacy) == legacy


def test_full_draft_publish_bind_flow_and_grant_environment_gates(bundle_dsn):
    registry = PostgresAgentRegistry(bundle_dsn, deployment_namespace="bundle-test")
    assembly = RuntimeAssembly.model_validate(assembly_payload())
    bundle_ref = "runtime-bundle/" + assembly.bundle.bundle_digest.removeprefix("sha256:") + "@1"
    ceiling = PublisherGrantCeiling(
        "https://business.example", "tenant/example", frozenset([*REFERENCES.values(), bundle_ref])
    )
    grants = StaticPublisherGrantResolver({"publisher@tenant/example": ceiling})
    service = AgentDefinitionDraftService(registry, grants)
    definition_id = AgentDefinitionId(uuid4())
    service.create_draft(
        definition_id=definition_id,
        namespace_id="tenant/example",
        actor_ref="publisher",
        name="native",
        description="frozen",
        skill_snapshot_digest="a" * 64,
        updated_at=NOW,
        **REFERENCES,
    )
    service.validate_draft(
        definition_id=definition_id,
        namespace_id="tenant/example",
        actor_ref="publisher",
        evaluated_at=NOW,
    )
    version = service.materialize_version(
        definition_id=definition_id,
        namespace_id="tenant/example",
        actor_ref="publisher",
        version_id=AgentDefinitionVersionId(uuid4()),
        version=1,
        created_at=NOW,
        runtime_assembly=assembly,
    )
    retried = service.materialize_version(
        definition_id=definition_id,
        namespace_id="tenant/example",
        actor_ref="publisher",
        version_id=version.version_id,
        version=1,
        created_at=NOW + timedelta(seconds=1),
        runtime_assembly=assembly,
    )
    assert retried == version and retried.created_at == NOW
    assert isinstance(version, BundleDefinitionVersion)
    assert registry.get_version(version.scope, version.version_id) == version
    publication = AgentDefinitionPublicationService(registry, grants)
    gate = PublicationGateEvidence(version.version_id, version.definition_digest, True, "policy/1")
    with pytest.raises(ValueError, match="environment"):
        publication.publish(
            version.scope,
            version_id=version.version_id,
            environment="production",
            actor_ref="publisher",
            gate=gate,
            effective_at=NOW,
        )
    badgate = PublicationGateEvidence(version.version_id, "0" * 64, True, "policy/1")
    with pytest.raises(ValueError, match="digest"):
        publication.publish(
            version.scope,
            version_id=version.version_id,
            environment="test",
            actor_ref="publisher",
            gate=badgate,
            effective_at=NOW,
        )
    publication.publish(
        version.scope,
        version_id=version.version_id,
        environment="test",
        actor_ref="publisher",
        gate=gate,
        effective_at=NOW,
    )
    binding = DefinitionBindingService(registry, grants)
    snapshot = binding.resolve_production_snapshot(
        version.scope, environment="test", resolved_at=NOW
    )
    assert parse_definition_snapshot(snapshot).bound_version == version
    assert (
        binding.resolve_eval_snapshot(
            version.scope,
            environment="test",
            version_id=version.version_id,
            actor_ref="publisher",
            resolved_at=NOW,
        ).bound_version
        == version
    )
    with pytest.raises(ValueError, match="environment"):
        binding.resolve_eval_snapshot(
            version.scope,
            environment="staging",
            version_id=version.version_id,
            actor_ref="publisher",
            resolved_at=NOW,
        )
    denied = StaticPublisherGrantResolver(
        {
            "publisher@tenant/example": PublisherGrantCeiling(
                ceiling.authority_issuer, ceiling.namespace_id, frozenset(REFERENCES.values())
            )
        }
    )
    with pytest.raises(PublisherGrantError, match="exact"):
        AgentDefinitionDraftService(registry, denied).materialize_version(
            definition_id=definition_id,
            namespace_id="tenant/example",
            actor_ref="publisher",
            version_id=AgentDefinitionVersionId(uuid4()),
            version=2,
            created_at=NOW,
            runtime_assembly=assembly,
        )


@pytest.mark.parametrize("corruption", ["missing", "content", "relational", "unknown"])
def test_corrupt_sidecar_or_base_fails_closed(bundle_dsn, corruption):
    registry = PostgresAgentRegistry(bundle_dsn, deployment_namespace="bundle-test")
    version = bundle_version()
    seed(registry, version)
    with psycopg.connect(bundle_dsn) as connection:
        if corruption == "missing":
            connection.execute(
                "DELETE FROM agent_definition_bundle_versions WHERE version_id=%s",
                (version.version_id,),
            )
        elif corruption == "relational":
            connection.execute(
                "UPDATE agent_definition_versions SET model_policy_ref='model/other@1' "
                "WHERE version_id=%s",
                (version.version_id,),
            )
        elif corruption == "unknown":
            connection.execute(
                "UPDATE agent_definition_versions SET schema_version='agent-definition/99' "
                "WHERE version_id=%s",
                (version.version_id,),
            )
        else:
            payload = version.model_dump(mode="json")
            payload["runtime_assembly"]["provider_profile"]["base_url"] = "https://other.example"
            connection.execute(
                "UPDATE agent_definition_bundle_versions SET snapshot=%s WHERE version_id=%s",
                (Jsonb(payload), version.version_id),
            )
    with pytest.raises(AgentRegistryStorageError):
        registry.get_version(version.scope, version.version_id)


def test_sidecar_failure_rolls_back_base_insert(bundle_dsn):
    registry = PostgresAgentRegistry(bundle_dsn, deployment_namespace="bundle-test")
    version = bundle_version()
    registry.save_definition(
        AgentDefinition(
            definition_id=version.definition_id,
            authority_issuer=version.authority_issuer,
            namespace_id=version.namespace_id,
            name="native",
            created_at=NOW,
        )
    )
    with psycopg.connect(bundle_dsn) as connection:
        connection.execute(
            "ALTER TABLE agent_definition_bundle_versions ADD CONSTRAINT "
            "forced_failure CHECK (false) NOT VALID"
        )
    try:
        with pytest.raises(psycopg.errors.CheckViolation):
            registry.save_version(version)
        assert registry.get_version(version.scope, version.version_id) is None
    finally:
        with psycopg.connect(bundle_dsn) as connection:
            connection.execute(
                "ALTER TABLE agent_definition_bundle_versions DROP CONSTRAINT forced_failure"
            )


def test_full_identity_conflicts_and_concurrent_idempotency(bundle_dsn):
    registry = PostgresAgentRegistry(bundle_dsn, deployment_namespace="bundle-test")
    version = bundle_version()
    seed(registry, version)
    replay = version.model_copy(update={"created_at": NOW + timedelta(seconds=1)})
    assert registry.save_version(replay) == version
    assert registry.get_version(version.scope, version.version_id) == version
    different = bundle_version(definition_id=version.definition_id, version=1)
    with pytest.raises(AgentRegistryStorageError, match="number"):
        registry.save_version(different)
    next_version = bundle_version(definition_id=version.definition_id, version=2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(registry.save_version, [next_version, next_version]))
    assert outcomes == [next_version, next_version]
    contenders = [bundle_version(definition_id=version.definition_id, version=3) for _ in range(2)]

    def save(candidate):
        try:
            registry.save_version(candidate)
            return "saved"
        except AgentRegistryStorageError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(save, contenders)) == ["conflict", "saved"]


def test_sqlite_and_postgres_workspace_parsers_roundtrip_frozen_v2(bundle_dsn, tmp_path):
    from agent_core.domain.bundle_definition import snapshot_from_version
    from agent_core.domain.identifiers import new_session_id
    from agent_core.domain.workspaces import WorkspaceProjection, WorkspaceStatus
    from agent_storage import SQLiteWorkspaceProjectionStore
    from agent_storage.postgres.workspaces import _workspace_from_row

    snapshot = snapshot_from_version(version=bundle_version(), resolved_at=NOW)
    workspace = WorkspaceProjection(
        session_id=new_session_id(),
        workspace_root="/tmp/bundle",
        prepared_at=NOW,
        updated_at=NOW,
        current_sequence=1,
        status=WorkspaceStatus.PREPARED,
        definition_snapshot=snapshot,
    )
    store = SQLiteWorkspaceProjectionStore(tmp_path / "workspace.db")
    store.save_workspace(workspace)
    assert store.get_workspace(workspace.session_id) == workspace
    # Exercise the real Postgres JSONB conversion boundary on the disposable database.
    with psycopg.connect(bundle_dsn) as connection:
        stored = connection.execute(
            "SELECT %s::jsonb", (Jsonb(snapshot.model_dump(mode="json")),)
        ).fetchone()[0]
    row = workspace.model_dump()
    row["definition_snapshot"] = stored
    row["network_allowlist"] = []
    assert _workspace_from_row(row).definition_snapshot == snapshot


@pytest.mark.parametrize("schema", ["agent-definition/1", "agent-definition/2"])
def test_created_at_retry_returns_original_without_overwriting_content(bundle_dsn, schema):
    registry = PostgresAgentRegistry(bundle_dsn, deployment_namespace="bundle-test")
    version = bundle_version()
    if schema == "agent-definition/1":
        version = AgentDefinitionVersion.model_validate(
            version.model_dump(
                exclude={"runtime_assembly", "schema_version", "definition_digest"},
            )
        )
    seed(registry, version)
    with psycopg.connect(bundle_dsn) as connection:
        before = connection.execute(
            "SELECT row_to_json(v)::text FROM agent_definition_versions v WHERE version_id=%s",
            (version.version_id,),
        ).fetchall()
        sidecar_before = connection.execute(
            "SELECT snapshot::text FROM agent_definition_bundle_versions WHERE version_id=%s",
            (version.version_id,),
        ).fetchall()
    replay = version.model_copy(update={"created_at": NOW + timedelta(seconds=1)})
    assert registry.save_version(replay) == version
    assert registry.get_version(version.scope, version.version_id) == version
    for changed_field, value in (("version", 2), ("model_policy_ref", "model/other@1")):
        payload = {**version.model_dump(), changed_field: value, "definition_digest": None}
        changed = type(version).model_validate(payload)
        with pytest.raises(AgentRegistryStorageError, match="reused"):
            registry.save_version(changed)
    with psycopg.connect(bundle_dsn) as connection:
        assert (
            connection.execute(
                "SELECT row_to_json(v)::text FROM agent_definition_versions v WHERE version_id=%s",
                (version.version_id,),
            ).fetchall()
            == before
        )
        assert (
            connection.execute(
                "SELECT snapshot::text FROM agent_definition_bundle_versions WHERE version_id=%s",
                (version.version_id,),
            ).fetchall()
            == sidecar_before
        )
