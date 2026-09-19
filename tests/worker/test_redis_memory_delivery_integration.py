from __future__ import annotations

import json
import os
from collections.abc import Generator
from dataclasses import replace
from typing import cast
from uuid import uuid4

import httpx
import psycopg
import pytest
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.memory_delivery import MemoryDeliveryScope
from agent_core.ports.agent_memory_gateway import MemoryGatewaySearchRequest
from agent_core.ports.artifact_object_store import ArtifactObjectStorePort
from agent_storage import PostgresGovernedMemoryStore, apply_postgres_migrations
from agent_storage.runtime_composition import CloudCompositionSettings
from psycopg import sql
from psycopg.conninfo import make_conninfo
from zebra_agent_config import MemoryGatewaySettings
from zebra_agent_worker.cloud_composition import compose_cloud_worker
from zebra_agent_worker.memory_context_materialization import RankedMemoryContextMaterializer
from zebra_agent_worker.memory_gateway_runtime import compose_memory_gateway_runtime

from tests.agent_storage.governed_memory_test_support import (
    CURSOR_SIGNING_KEY,
    authority,
    candidate,
    plan,
    prepare_environment,
)


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get("ZEBRA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ZEBRA_TEST_POSTGRES_DSN to run real PostgreSQL tests")
    return dsn


@pytest.fixture
def dsn(postgres_dsn: str) -> Generator[str]:
    schema = f"redis_memory_{uuid4().hex}"
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(postgres_dsn, options=f"-c search_path={schema}")
    apply_postgres_migrations(isolated)
    yield isolated
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_governed_commit_delivers_and_recall_requires_durable_mapping(dsn: str) -> None:
    environment = prepare_environment(dsn)
    scope = MemoryDeliveryScope(
        deployment_namespace=environment.namespace,
        scope_digest="e" * 64,
        generation=1,
        revision=0,
    )
    store = PostgresGovernedMemoryStore(
        dsn,
        deployment_namespace=environment.namespace,
        cursor_signing_key=CURSOR_SIGNING_KEY,
        delivery_scope=scope,
    )
    environment = replace(environment, store=store)
    records: dict[str, dict[str, str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            memory_id = request.url.path.rsplit("/", 1)[-1]
            return _json(200, records[memory_id]) if memory_id in records else _json(404, {})
        body = json.loads(request.content)
        if request.url.path.endswith("/search"):
            return _json(200, {"items": list(records.values())})
        record = body["memories"][0]
        records[record["id"]] = record
        return _json(201, {"created": [record["id"]]})

    runtime = compose_memory_gateway_runtime(
        MemoryGatewaySettings(
            provider="redis_agent_memory",
            rollout="shadow",
            endpoint="https://memory.example",
            store_id="store-a",
            data_export_authorized=True,
        ),
        dsn=dsn,
        deployment_namespace=environment.namespace,
        authority=store,
        scope=scope,
        environ={"REDIS_AGENT_MEMORY_API_KEY": "secret"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert runtime is not None
    record = candidate(environment, text="Deploy only after the release gate passes.")
    store.commit_worker_candidates(
        plan(
            environment,
            operation_id="redis-memory-delivery",
            expected_revision=1,
            records=(record,),
            confirmed=(record.memory_id,),
        ),
        authority=authority(environment, 1),
    )

    delivered = runtime.consume_once("worker-a")
    search = runtime.gateway.search(
        MemoryGatewaySearchRequest(
            namespace=f"{scope.scope_digest}:{scope.generation}",
            query="release gate",
            limit=5,
        )
    )
    admitted = runtime.ledger.revalidate_search_hits(
        runtime.scope,
        ((hit.memory_id, hit.provider_ref) for hit in search.hits),
    )

    assert delivered.status == "completed"
    assert list(records) == [str(record.memory_id)]
    assert [item.memory_id for item in admitted] == [record.memory_id]


def test_cloud_composition_wires_scope_delivery_and_ranked_context(dsn: str) -> None:
    namespace = f"redis-composition-{uuid4()}"
    scope = OpaqueAuthorityScope(authority_issuer="issuer", namespace_id="scope")
    cloud = CloudCompositionSettings(
        dsn=dsn,
        deployment_namespace=namespace,
        memory_cursor_signing_key=b"redis-composition-signing-key-32",
        artifact_objects=cast(ArtifactObjectStorePort, _ObjectStore()),
        history_scope=scope,
        continuation_scope=scope,
    )
    composition = compose_cloud_worker(
        cloud,
        memory_settings=MemoryGatewaySettings(
            provider="redis_agent_memory",
            rollout="active",
            endpoint="https://memory.example",
            store_id="store-a",
            data_export_authorized=True,
        ),
        memory_environ={"REDIS_AGENT_MEMORY_API_KEY": "secret"},
        memory_http_client=httpx.Client(transport=httpx.MockTransport(lambda _: _json(500, {}))),
    )

    assert composition.memory_runtime is not None
    assert composition.memory_runtime.rollout == "active"
    assert isinstance(
        composition.stores.context_materialization,
        RankedMemoryContextMaterializer,
    )
    with psycopg.connect(dsn) as connection:
        assert connection.execute(
            """SELECT count(*) FROM memory_delivery_scopes
            WHERE deployment_namespace = %s""",
            (namespace,),
        ).fetchone() == (1,)


def _json(status: int, payload: object) -> httpx.Response:
    return httpx.Response(status, json=payload)


class _ObjectStore:
    def put_if_absent(self, request: object) -> object:
        raise AssertionError(request)

    def verify(self, expectation: object) -> object:
        raise AssertionError(expectation)

    def read_verified(self, expectation: object) -> bytes:
        raise AssertionError(expectation)

    def read_version_verified(self, expectation: object, version: str) -> bytes:
        raise AssertionError((expectation, version))

    def delete_if_version(self, expectation: object, version: str) -> object:
        raise AssertionError((expectation, version))
