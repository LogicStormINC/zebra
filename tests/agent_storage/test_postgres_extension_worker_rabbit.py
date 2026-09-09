"""Production composition: PostgreSQL admission -> Rabbit -> cloud Skill read."""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace

import psycopg
import pytest
from agent_core.application.extension_configuration import set_extension_enabled
from agent_core.application.skill_installations import create_skill_installation
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventType
from agent_core.domain.extensions import ExtensionScope
from agent_core.domain.sessions import SessionStatus
from agent_core.domain.skill_publications import publication_identity
from agent_core.domain.turns import InteractionMode
from agent_storage import CloudCompositionSettings
from agent_storage.postgres.extension_snapshots import PostgresExtensionSnapshotStore
from agent_storage.postgres.extensions import PostgresExtensionStore
from agent_storage.postgres.skill_publications import PostgresSkillPublicationStore
from agent_tools.skill_publications import publish_skill_package
from zebra_agent_api.command_submission import submit_session_command
from zebra_agent_api.extension_turn_admission import CloudExtensionTurnAdmission
from zebra_agent_config.command_delivery import CommandDeliverySettings
from zebra_agent_worker.loop import build_worker_loop_service

from tests.agent_storage import test_postgres_default_chain_e2e as model_stub
from tests.agent_storage import test_skill_publication_minio as publication_fixtures
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE
from tests.agent_storage.test_postgres_command_wakeup_execution import _setup
from tests.agent_storage.test_postgres_extension_turn_admission import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_extension_turn_admission import (
    postgres_dsn as _pg_fixture,
)
from tests.agent_storage.test_postgres_extension_worker_handoff import (
    _scope,
    _verified_from_ceiling,
)

dsn = _dsn_fixture
postgres_dsn = _pg_fixture
objects = publication_fixtures.objects


def _rabbit_urls() -> tuple[str, str]:
    relay = os.environ.get("ZEBRA_TEST_RABBIT_RELAY_URL")
    consumer = os.environ.get("ZEBRA_TEST_RABBIT_CONSUMER_URL")
    if not relay or not consumer:
        pytest.skip("set ZEBRA_TEST_RABBIT_*_URL to run the real Rabbit Worker test")
    return relay, consumer


def test_production_loop_executes_bound_skill_read_through_rabbit(
    dsn: str,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    objects,
    stub_model_server: str,
) -> None:
    """No service mutation: build_worker_loop_service owns every cloud dependency."""
    from zebra_agent_worker import execution as execution_module

    original_build_model_gateway = execution_module.build_model_gateway
    extension_scope = ExtensionScope(
        authority_issuer="https://trench.example",
        namespace_id="tenant-a",
        principal_id="user-a",
        workspace_id="workspace-a",
    )
    skill_id = publication_identity(NAMESPACE, extension_scope, "sample", "1.0")[0]
    initial_service, stores, first_lease = _setup(
        dsn,
        tmp_path,
        monkeypatch,
        interaction_mode=InteractionMode.CONVERSATION,
        skill_components=(skill_id,),
        manifest_digest="0" * 64,
    )
    assert (
        initial_service.execute_claimed_session(first_lease).session.status
        is SessionStatus.AWAITING_TURN
    )
    monkeypatch.setattr(execution_module, "build_model_gateway", original_build_model_gateway)

    snapshots = PostgresExtensionSnapshotStore(dsn, deployment_namespace=NAMESPACE)
    ceiling = snapshots.resolve_task_ceiling(session_id=str(first_lease.session_id))
    assert _scope(ceiling) == extension_scope
    extensions = PostgresExtensionStore(dsn, deployment_namespace=NAMESPACE)

    async def publish_and_install():
        publication = await publish_skill_package(
            archive=publication_fixtures._archive("PRODUCTION-RABBIT-SKILL"),
            scope=extension_scope,
            deployment_namespace=NAMESPACE,
            store=PostgresSkillPublicationStore(dsn, deployment_namespace=NAMESPACE),
            objects=objects,
        )
        installation, _ = await create_skill_installation(
            store=extensions,
            scope=extension_scope,
            idempotency_key="production-rabbit-skill",
            payload={
                "skill_id": publication.version.skill_id,
                "version_id": publication.version.version_id,
            },
        )
        return await set_extension_enabled(
            store=extensions,
            scope=extension_scope,
            kind="skill",
            object_id=installation.installation_id,
            expected_revision=1,
            enabled=True,
        )

    asyncio.run(publish_and_install())
    admission = CloudExtensionTurnAdmission(extensions, snapshots, snapshots)
    current = stores.sessions.get_session(first_lease.session_id)
    response = submit_session_command(
        stores,
        str(first_lease.session_id),
        {
            "kind": "message",
            "expected_revision": current.current_sequence,
            "payload": {"content": "Read the installed cloud skill."},
        },
        idempotency_key="production-rabbit-message",
        extension_admission=admission,
        verified_host_grant=_verified_from_ceiling(ceiling),
    )
    assert response.status_code == 202
    accepted = next(
        event
        for event in reversed(stores.events.list_for_session(first_lease.session_id))
        if event.event_type is EventType.SESSION_COMMAND_ACCEPTED
        and event.idempotency_key == "production-rabbit-message"
    )
    assert accepted.payload["extension_snapshot_digest"]

    model_requests: list[set[str]] = []

    def scripted(body):
        messages = body.get("messages", [])
        tools = body.get("tools", [])
        advertised = {
            tool.get("function", {}).get("name") for tool in tools if isinstance(tool, dict)
        }
        model_requests.append({name for name in advertised if isinstance(name, str)})
        skill_read = next(
            (
                name
                for name in advertised
                if isinstance(name, str) and "skills" in name and "read" in name
            ),
            None,
        )
        if skill_read and not any(
            isinstance(message, dict) and message.get("role") == "tool" for message in messages
        ):
            return model_stub._tool_completion("skill-read", skill_read, {"name": "sample"})
        return model_stub._completion("Production Rabbit Skill read completed.")

    monkeypatch.setattr(model_stub, "_scripted_response", scripted)
    relay_url, consumer_url = _rabbit_urls()
    settings = replace(
        model_stub._settings(stub_model_server, dsn),
        cloud_extension_worker_enabled=True,
        cloud_skill_worker_enabled=True,
        command_delivery=CommandDeliverySettings(
            publish_enabled=True,
            consume_enabled=True,
            scan_fallback_enabled=False,
            relay_url=relay_url,
            consumer_url=consumer_url,
            execution_slots=1,
            batch_size=1,
            tick_seconds=0.05,
            transport_timeout=5,
        ),
    )
    authority = OpaqueAuthorityScope(
        authority_issuer=extension_scope.authority_issuer,
        namespace_id=extension_scope.namespace_id,
    )
    cloud = CloudCompositionSettings(
        dsn=dsn,
        deployment_namespace=NAMESPACE,
        memory_cursor_signing_key=b"x" * 32,
        artifact_objects=objects,
        history_scope=authority,
        continuation_scope=authority,
    )
    loop = build_worker_loop_service(
        database_path=tmp_path / "unused-production.sqlite",
        settings=settings,
        cloud_composition=cloud,
    )
    assert loop.migrated_run is not None
    result = loop.run(
        worker_id="production-rabbit-skill-worker",
        batch_size=1,
        lease_ttl_seconds=30,
        max_cycles=100,
        idle_sleep_seconds=0.05,
    )

    events = stores.events.list_for_session(first_lease.session_id)
    assert result.skipped_session_ids == (), result
    assert model_requests, [event.event_type.value for event in events]
    assert any(
        any("skills" in name and "read" in name for name in request) for request in model_requests
    ), model_requests
    tool = next(
        event
        for event in events
        if event.event_type is EventType.TOOL_EXECUTION_COMPLETED
        and event.payload.get("tool_name") == "skills.read"
    )
    assert "PRODUCTION-RABBIT-SKILL" in tool.payload["output"]
    with psycopg.connect(dsn) as connection:
        row = connection.execute(
            "SELECT status FROM broker_outbox WHERE operation_id=%s",
            (accepted.payload["command_id"],),
        ).fetchone()
    assert row == ("published",)
