from __future__ import annotations

import json
from uuid import UUID

import httpx
import pytest
from agent_core.domain.identifiers import MemoryId
from agent_core.domain.memory_delivery import MemoryDeliveryCertainty
from agent_core.ports.agent_memory_gateway import (
    ConfirmedMemoryPublication,
    MemoryGatewayDeleteRequest,
    MemoryGatewaySearchRequest,
    MemoryGatewayStatus,
)
from agent_integrations.redis_agent_memory import (
    RedisAgentMemoryConfig,
    RedisAgentMemoryGateway,
    encode_owner_id,
)

MEMORY_ID = MemoryId(UUID("00000000-0000-0000-0000-000000000901"))
NAMESPACE = "authority:scope:1"
OWNER_ID = encode_owner_id(NAMESPACE)


def test_config_is_disabled_safe_and_requires_tls_credentials() -> None:
    assert RedisAgentMemoryConfig().enabled is False
    with pytest.raises(ValueError, match="endpoint, store_id and api_key"):
        RedisAgentMemoryConfig(enabled=True)
    with pytest.raises(ValueError, match="explicit allow_insecure_http"):
        RedisAgentMemoryConfig(
            enabled=True,
            base_url="http://memory.example",
            store_id="store-a",
            api_key="secret",
        )
    config = RedisAgentMemoryConfig(
        enabled=True,
        base_url="https://memory.example/",
        store_id="store-a",
        api_key="secret",
    )
    assert config.base_url == "https://memory.example"
    assert "secret" not in repr(config)


def test_publish_creates_with_stable_id_and_replays_without_second_write() -> None:
    records: dict[str, dict[str, str]] = {}
    writes = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal writes
        _assert_auth(request)
        if request.method == "GET":
            memory_id = request.url.path.rsplit("/", 1)[-1]
            return _json(200, records[memory_id]) if memory_id in records else _json(404, {})
        body = json.loads(request.content)
        record = body["memories"][0]
        writes += 1
        records[record["id"]] = record
        return _json(201, {"created": [record["id"]]})

    gateway = _gateway(handler)
    first = gateway.publish(_publication("first text"))
    replay = gateway.publish(_publication("first text"))

    assert first.provider_ref == str(MEMORY_ID)
    assert replay.detail == "replayed"
    assert writes == 1
    assert records[str(MEMORY_ID)]["ownerId"] == OWNER_ID


def test_publish_updates_a_new_governed_revision_in_place() -> None:
    record = _record("old text")

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal record
        if request.method == "GET":
            return _json(200, record)
        assert request.method == "PATCH"
        record = {**record, **json.loads(request.content)}
        return _json(200, record)

    result = _gateway(handler).publish(_publication("new text"))

    assert result.status is MemoryGatewayStatus.SUCCEEDED
    assert record["text"] == "new text"


def test_publish_recovers_after_response_loss_without_duplicate_write() -> None:
    record: dict[str, str] | None = None
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal record, calls
        calls += 1
        if request.method == "GET":
            return _json(404, {}) if record is None else _json(200, record)
        body = json.loads(request.content)["memories"][0]
        record = body
        raise httpx.ReadTimeout("response lost", request=request)

    result = _gateway(handler).publish(_publication("durable text"))

    assert result.status is MemoryGatewayStatus.SUCCEEDED
    assert result.detail == "reconciled_after_response_loss"
    assert calls == 3


def test_scope_collision_is_definite_no_effect_and_never_mutates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return _json(200, {**_record("text"), "ownerId": "another-owner"})

    result = _gateway(handler).publish(_publication("text"))

    assert result.status is MemoryGatewayStatus.DEGRADED
    assert result.certainty is MemoryDeliveryCertainty.DEFINITE_NO_EFFECT
    assert result.detail == "memory_id_scope_collision"


def test_malformed_lookup_is_unknown_and_never_attempts_a_write() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.method == "GET"
        return httpx.Response(200, content=b"not-json")

    result = _gateway(handler).publish(_publication("text"))

    assert result.certainty is MemoryDeliveryCertainty.UNKNOWN
    assert result.detail == "invalid_response"
    assert calls == 1


def test_delete_reconciles_a_lost_response_to_absence() -> None:
    record: dict[str, str] | None = _record("text")

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal record
        if request.method == "GET":
            return _json(404, {}) if record is None else _json(200, record)
        record = None
        raise httpx.ReadTimeout("response lost", request=request)

    result = _gateway(handler).delete(
        MemoryGatewayDeleteRequest(
            memory_id=MEMORY_ID,
            namespace=NAMESPACE,
            idempotency_key="delete-1",
        )
    )

    assert result.status is MemoryGatewayStatus.SUCCEEDED
    assert result.detail == "reconciled_after_delete"


def test_unreconciled_timeout_stays_unknown() -> None:
    record = _record("text")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _json(200, record)
        raise httpx.ReadTimeout("response lost", request=request)

    result = _gateway(handler).delete(
        MemoryGatewayDeleteRequest(
            memory_id=MEMORY_ID,
            namespace=NAMESPACE,
            idempotency_key="delete-2",
        )
    )

    assert result.status is MemoryGatewayStatus.DEGRADED
    assert result.certainty is MemoryDeliveryCertainty.UNKNOWN


def test_search_sends_strict_owner_filter_and_discards_cross_scope_hits() -> None:
    other_id = "00000000-0000-0000-0000-000000000902"

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["filter"] == {"ownerId": {"eq": OWNER_ID}}
        return _json(
            200,
            {
                "items": [
                    _record("matching"),
                    {"id": other_id, "text": "wrong", "ownerId": "another-owner"},
                ]
            },
        )

    result = _gateway(handler).search(
        MemoryGatewaySearchRequest(namespace=NAMESPACE, query="matching", limit=5)
    )

    assert result.status is MemoryGatewayStatus.PARTIAL
    assert [hit.memory_id for hit in result.hits] == [MEMORY_ID]
    assert result.detail == "discarded_invalid_hits=1"


def test_disabled_gateway_has_no_network_side_effect() -> None:
    gateway = RedisAgentMemoryGateway(RedisAgentMemoryConfig())
    assert gateway.publish(_publication("text")).status is MemoryGatewayStatus.DISABLED
    assert (
        gateway.search(MemoryGatewaySearchRequest(namespace=NAMESPACE, query="text")).status
        is MemoryGatewayStatus.DISABLED
    )


def _gateway(handler) -> RedisAgentMemoryGateway:  # noqa: ANN001
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return RedisAgentMemoryGateway(
        RedisAgentMemoryConfig(
            enabled=True,
            base_url="https://memory.example",
            store_id="store-a",
            api_key="secret",
        ),
        client=client,
    )


def _publication(text: str) -> ConfirmedMemoryPublication:
    return ConfirmedMemoryPublication(
        memory_id=MEMORY_ID,
        namespace=NAMESPACE,
        text=text,
        idempotency_key="publish-1",
    )


def _record(text: str) -> dict[str, str]:
    return {"id": str(MEMORY_ID), "text": text, "ownerId": OWNER_ID}


def _json(status: int, payload: object) -> httpx.Response:
    return httpx.Response(status, json=payload)


def _assert_auth(request: httpx.Request) -> None:
    assert request.headers["Authorization"] == "Bearer secret"
    assert request.url.path.startswith("/v1/stores/store-a/long-term-memory")
