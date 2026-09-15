from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

import httpx
import jwt
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import TaskScheduleId
from agent_core.domain.task_bindings import host_context_digest
from agent_core.domain.task_schedule_authority import (
    ScheduleAuthorityBinding,
    ScheduledTaskTemplate,
    ScheduleOwner,
)
from agent_core.domain.task_schedules import (
    DailyScheduleTrigger,
    TaskSchedule,
    TaskScheduleFiring,
)
from agent_integrations import HttpScheduleAuthorityRevalidator, ScheduleGrantExchangeSettings
from agent_security import HostGrantVerificationConfig, JwtAlgorithm, PyJwtHostGrantDecoder
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from zebra_host_grant_broker.app import create_app
from zebra_host_grant_broker.config import BrokerSettings
from zebra_host_grant_broker.keys import jwk_document

NOW = datetime.now(UTC)


class StaticJwks:
    def __init__(self, key: object, key_id: str) -> None:
        self.document = jwk_document(key, key_id)

    def resolve(self, _jwks_uri: str, _token: str) -> object:
        return jwt.PyJWK.from_dict({"alg": "RS256", **self.document}).key


def broker_settings(key: object) -> BrokerSettings:
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return BrokerSettings(
        issuer="https://broker.example",
        audience="zebra",
        host_app_id="trench",
        namespace_id="tenant-1",
        workspace_ref="workspace-1",
        origin="https://trench.example",
        policy_version="policy-v1",
        allowed_scopes=("agent.run", "schedule.manage", "source.read"),
        private_key_pem=pem,
        key_id="schedule-test",
        ttl_seconds=300,
        trench_me_url="https://trench.example/me",
        trench_sources_url="https://trench.example/sources",
        trench_timeout_seconds=5,
        max_runtime_seconds=1800,
        max_model_tokens=1_000_000,
        max_artifact_bytes=64_000_000,
        workload_identities=("scheduler",),
        workload_shared_secret="workload-secret",
    )


def authority_fixture() -> tuple[ScheduleAuthorityBinding, TaskScheduleFiring]:
    owner = ScheduleOwner(
        deployment_namespace="cloud",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        principal_id="user-1",
        host_app_id="trench",
    )
    context = HostContextEnvelope(
        grant_id="login-grant",
        host_app_id="trench",
        namespace_id="tenant-1",
        workspace_ref="workspace-1",
        resource_refs=(
            {"type": "principal", "id": "user-1"},
            {"type": "trench.source", "id": "source-1"},
        ),
        scopes=("agent.run", "schedule.manage", "source.read"),
        limits={
            "max_runtime_seconds": 1800,
            "max_model_tokens": 1_000_000,
            "max_artifact_bytes": 64_000_000,
        },
        origin="https://trench.example",
        policy_version="policy-v1",
    )
    schedule_id = TaskScheduleId(uuid4())
    binding_id = uuid4()
    schedule = TaskSchedule(
        schedule_id=schedule_id,
        owner=owner,
        title="Daily",
        timezone="Asia/Shanghai",
        trigger=DailyScheduleTrigger(local_time=time(9)),
        task_template=ScheduledTaskTemplate(payload={"prompt": "Daily report"}),
        authority_binding_id=binding_id,
        schedule_version=1,
        next_fire_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    binding = ScheduleAuthorityBinding(
        binding_id=binding_id,
        schedule_id=schedule_id,
        owner=owner,
        host_context=context,
        host_capability_digest=host_context_digest(context),
        agent_definition_digest="0" * 64,
        policy_digest="b" * 64,
        extension_snapshot_digest="c" * 64,
        binding_revision=1,
        bound_at=NOW,
    )
    firing = TaskScheduleFiring(
        fire_id=uuid4(),
        schedule_id=schedule_id,
        schedule_version=1,
        schedule_snapshot=schedule,
        scheduled_for=NOW,
        attempt=1,
        claimed_by="scheduler",
        claim_expires_at=NOW + timedelta(minutes=1),
        created_at=NOW,
    )
    return binding, firing


def test_schedule_exchange_mints_and_verifies_fresh_narrowed_authority() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    broker = broker_settings(key)
    test_client = TestClient(create_app(broker))

    def exchange(request: httpx.Request) -> httpx.Response:
        result = test_client.post(
            request.url.path, content=request.content, headers=dict(request.headers)
        )
        assert result.status_code == 200, result.text
        return httpx.Response(result.status_code, content=result.content)

    verification = HostGrantVerificationConfig(
        issuer=broker.issuer,
        audience=broker.audience,
        jwks_uri="https://broker.example/.well-known/jwks.json",
        allowed_origins=(broker.origin,),
        algorithms=frozenset({JwtAlgorithm.RS256}),
    )
    client = httpx.Client(transport=httpx.MockTransport(exchange))
    adapter = HttpScheduleAuthorityRevalidator(
        ScheduleGrantExchangeSettings(
            exchange_url="https://broker.example/exchange",
            workload_identity="scheduler",
            workload_shared_secret="workload-secret",
            verification=verification,
        ),
        PyJwtHostGrantDecoder(StaticJwks(key, broker.key_id)),
        client=client,
        now=lambda: NOW,
    )
    binding, firing = authority_fixture()

    fresh = adapter.revalidate(binding, firing)

    assert fresh.host_context.grant_id != binding.host_context.grant_id
    assert "schedule.manage" not in fresh.host_context.scopes
    assert "agent.run" in fresh.host_context.scopes
    assert ("trench.source", "source-1") in {ref.key for ref in fresh.host_context.resource_refs}
