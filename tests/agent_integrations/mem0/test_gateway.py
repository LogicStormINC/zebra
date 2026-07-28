from __future__ import annotations

import json
from collections.abc import Callable
from uuid import uuid4

import httpx
import pytest
from agent_core.domain.identifiers import MemoryId
from agent_core.ports.agent_memory_gateway import (
    ConfirmedMemoryPublication,
    MemoryGatewayDeleteRequest,
    MemoryGatewaySearchRequest,
    MemoryGatewayStatus,
)
from agent_integrations.mem0 import (
    Mem0AgentMemoryGateway,
    Mem0GatewayConfig,
    Mem0ProviderRefLookup,
    encode_mem0_namespace,
)

NAMESPACE = "opaque-tenant/repository/user"
API_KEY = "secret-mem0-key"
PROVIDER_ID = "018f0000-0000-7000-8000-000000000101"
SECOND_PROVIDER_ID = "018f0000-0000-7000-8000-000000000102"


def test_disabled_gateway_requires_no_credentials_or_network() -> None:
    gateway = Mem0AgentMemoryGateway(Mem0GatewayConfig())

    assert gateway.publish(_publication()).status is MemoryGatewayStatus.DISABLED
    assert gateway.search(_search_request()).status is MemoryGatewayStatus.DISABLED
    assert gateway.delete(_delete_request()).status is MemoryGatewayStatus.DISABLED


def test_enabled_config_validates_endpoint_and_hides_api_key() -> None:
    config = _config(base_url=" http://mem0-api:8080/ ")

    assert config.base_url == "http://mem0-api:8080"
    assert API_KEY not in repr(config)

    with pytest.raises(ValueError, match="absolute HTTP URL"):
        _config(base_url="mem0-api:8080")
    with pytest.raises(ValueError, match="must not contain credentials"):
        Mem0GatewayConfig(
            enabled=True,
            base_url="https://user:password@mem0.example",
            api_key=API_KEY,
        )
    with pytest.raises(ValueError, match="explicit allow_insecure_http"):
        Mem0GatewayConfig(
            enabled=True,
            base_url="http://remote.example",
            api_key=API_KEY,
        )


def test_publish_uses_infer_false_and_opaque_namespace() -> None:
    seen: list[httpx.Request] = []
    publication = _publication()

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={"results": [{"id": PROVIDER_ID, "event": "ADD"}]},
        )

    result = _gateway(handler).publish(publication)

    assert result.status is MemoryGatewayStatus.SUCCEEDED
    assert result.provider_ref == PROVIDER_ID
    assert len(seen) == 1
    request = seen[0]
    assert request.url == "http://mem0.test/memories"
    assert request.headers["X-API-Key"] == API_KEY
    payload = json.loads(request.content)
    assert payload == {
        "messages": [{"role": "user", "content": "confirmed fact"}],
        "user_id": encode_mem0_namespace(NAMESPACE),
        "metadata": {
            "zebra_memory_id": str(publication.memory_id),
            "zebra_idempotency_key": "delivery-1",
            "zebra_schema_version": 1,
        },
        "infer": False,
    }


def test_search_returns_only_revalidatable_hits_and_marks_partial() -> None:
    namespace = encode_mem0_namespace(NAMESPACE)
    valid_memory_id = str(_memory_id())

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload == {
            "query": "concise",
            "filters": {"user_id": namespace},
            "top_k": 7,
        }
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": PROVIDER_ID,
                        "memory": "must never escape the adapter",
                        "score": 0.75,
                        "user_id": namespace,
                        "metadata": {"zebra_memory_id": valid_memory_id},
                    },
                    {
                        "id": SECOND_PROVIDER_ID,
                        "score": 1.0,
                        "user_id": encode_mem0_namespace("other-scope"),
                        "metadata": {"zebra_memory_id": str(uuid4())},
                    },
                ]
            },
        )

    result = _gateway(handler).search(
        MemoryGatewaySearchRequest(namespace=NAMESPACE, query="concise", limit=7)
    )

    assert result.status is MemoryGatewayStatus.PARTIAL
    assert result.detail == "discarded_invalid_hits=1"
    assert len(result.hits) == 1
    assert str(result.hits[0].memory_id) == valid_memory_id
    assert result.hits[0].provider_ref == PROVIDER_ID
    assert result.hits[0].provider_score == 0.75
    assert "memory" not in result.hits[0].model_dump()


@pytest.mark.parametrize(
    ("response", "expected_detail"),
    [
        (httpx.Response(429, json={"detail": "raw rate-limit body"}), "rate_limited"),
        (httpx.Response(503, json={"detail": "raw provider body"}), "provider_unavailable"),
        (httpx.Response(200, content=b"{"), "invalid_response"),
        (httpx.Response(200, json={"unexpected": []}), "invalid_response"),
    ],
)
def test_search_normalizes_provider_failures_without_raw_body(
    response: httpx.Response,
    expected_detail: str,
) -> None:
    result = _gateway(lambda request: response).search(_search_request())

    assert result.status is MemoryGatewayStatus.DEGRADED
    assert result.detail == expected_detail
    assert "raw" not in repr(result)
    assert API_KEY not in repr(result)


def test_timeout_is_a_degraded_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider stalled", request=request)

    result = _gateway(handler).search(_search_request())

    assert result.status is MemoryGatewayStatus.DEGRADED
    assert result.detail == "provider_timeout"


def test_circuit_opens_and_recovers_after_bounded_failures() -> None:
    now = [10.0]
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls <= 2:
            return httpx.Response(503, json={})
        return httpx.Response(200, json={"results": []})

    gateway = _gateway(
        handler,
        config=_config(circuit_failure_threshold=2, circuit_recovery_seconds=5),
        clock=lambda: now[0],
    )

    assert gateway.search(_search_request()).detail == "provider_unavailable"
    assert gateway.search(_search_request()).detail == "provider_unavailable"
    assert gateway.search(_search_request()).detail == "circuit_open"
    assert calls == 2

    now[0] += 5
    recovered = gateway.search(_search_request())
    assert recovered.status is MemoryGatewayStatus.SUCCEEDED
    assert calls == 3


def test_repeated_schema_drift_opens_circuit() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"unexpected": []})

    gateway = _gateway(handler, config=_config(circuit_failure_threshold=2))

    assert gateway.search(_search_request()).detail == "invalid_response"
    assert gateway.search(_search_request()).detail == "invalid_response"
    assert gateway.search(_search_request()).detail == "circuit_open"
    assert calls == 2


def test_repeated_all_invalid_hits_open_circuit() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"results": [{"unexpected": "shape"}]})

    gateway = _gateway(handler, config=_config(circuit_failure_threshold=2))

    assert gateway.search(_search_request()).detail == "invalid_response"
    assert gateway.search(_search_request()).detail == "invalid_response"
    assert gateway.search(_search_request()).detail == "circuit_open"
    assert calls == 2


def test_search_caps_excess_provider_hits() -> None:
    namespace = encode_mem0_namespace(NAMESPACE)
    raw_hits = [
        {
            "id": provider_id,
            "user_id": namespace,
            "metadata": {"zebra_memory_id": str(uuid4())},
        }
        for provider_id in (PROVIDER_ID, SECOND_PROVIDER_ID)
    ]
    result = _gateway(
        lambda request: httpx.Response(200, json={"results": raw_hits})
    ).search(MemoryGatewaySearchRequest(namespace=NAMESPACE, query="fact", limit=1))

    assert result.status is MemoryGatewayStatus.PARTIAL
    assert len(result.hits) == 1
    assert result.detail == "discarded_excess_hits=1"


def test_delete_uses_namespace_scoped_provider_ref_lookup() -> None:
    lookup = _ProviderRefs(provider_ref=PROVIDER_ID.upper())
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    request = _delete_request()
    result = _gateway(handler, provider_refs=lookup).delete(request)

    assert lookup.seen == [(request.memory_id, NAMESPACE)]
    assert result.status is MemoryGatewayStatus.SUCCEEDED
    assert result.provider_ref == PROVIDER_ID
    assert seen[0].method == "DELETE"
    assert seen[0].url == f"http://mem0.test/memories/{PROVIDER_ID}"


def test_delete_without_mapping_is_not_found_without_network() -> None:
    result = _gateway(
        lambda request: pytest.fail("network must not be called"),
        provider_refs=_ProviderRefs(provider_ref=None),
    ).delete(_delete_request())

    assert result.status is MemoryGatewayStatus.NOT_FOUND
    assert result.detail == "provider_ref_not_found"


def test_delete_without_lookup_is_degraded_without_network() -> None:
    result = _gateway(lambda request: pytest.fail("network must not be called")).delete(
        _delete_request()
    )

    assert result.status is MemoryGatewayStatus.DEGRADED
    assert result.detail == "provider_ref_lookup_unavailable"


def test_delete_lookup_failure_is_degraded_without_network() -> None:
    result = _gateway(
        lambda request: pytest.fail("network must not be called"),
        provider_refs=_FailingProviderRefs(),
    ).delete(_delete_request())

    assert result.status is MemoryGatewayStatus.DEGRADED
    assert result.detail == "provider_ref_lookup_unavailable"


@pytest.mark.parametrize("provider_ref", ["../reset", "provider?id", "not-a-uuid"])
def test_delete_rejects_non_uuid_provider_refs(provider_ref: str) -> None:
    result = _gateway(
        lambda request: pytest.fail("network must not be called"),
        provider_refs=_ProviderRefs(provider_ref=provider_ref),
    ).delete(_delete_request())

    assert result.status is MemoryGatewayStatus.DEGRADED
    assert result.detail == "invalid_provider_ref"


def test_delete_maps_provider_404_to_not_found() -> None:
    result = _gateway(
        lambda request: httpx.Response(404, json={}),
        provider_refs=_ProviderRefs(provider_ref=PROVIDER_ID),
    ).delete(_delete_request())

    assert result.status is MemoryGatewayStatus.NOT_FOUND
    assert result.detail == "provider_memory_not_found"


def test_provider_response_is_size_bounded() -> None:
    result = _gateway(
        lambda request: httpx.Response(200, content=b"x" * (4 * 1_024 * 1_024 + 1))
    ).search(_search_request())

    assert result.status is MemoryGatewayStatus.DEGRADED
    assert result.detail == "response_too_large"


class _ProviderRefs:
    def __init__(self, *, provider_ref: str | None) -> None:
        self.provider_ref = provider_ref
        self.seen: list[tuple[MemoryId, str]] = []

    def resolve(self, *, memory_id: MemoryId, namespace: str) -> str | None:
        self.seen.append((memory_id, namespace))
        return self.provider_ref


class _FailingProviderRefs:
    def resolve(self, *, memory_id: MemoryId, namespace: str) -> str | None:
        raise RuntimeError("ledger offline")


def _memory_id() -> MemoryId:
    return MemoryId(uuid4())


def _publication() -> ConfirmedMemoryPublication:
    return ConfirmedMemoryPublication(
        memory_id=_memory_id(),
        namespace=NAMESPACE,
        text="confirmed fact",
        idempotency_key="delivery-1",
    )


def _search_request() -> MemoryGatewaySearchRequest:
    return MemoryGatewaySearchRequest(namespace=NAMESPACE, query="concise")


def _delete_request() -> MemoryGatewayDeleteRequest:
    return MemoryGatewayDeleteRequest(
        memory_id=_memory_id(),
        namespace=NAMESPACE,
        idempotency_key="delete-1",
    )


def _config(
    *,
    base_url: str = "http://mem0.test",
    circuit_failure_threshold: int = 3,
    circuit_recovery_seconds: float = 30,
) -> Mem0GatewayConfig:
    return Mem0GatewayConfig(
        enabled=True,
        base_url=base_url,
        api_key=API_KEY,
        allow_insecure_http=True,
        circuit_failure_threshold=circuit_failure_threshold,
        circuit_recovery_seconds=circuit_recovery_seconds,
    )


def _gateway(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    config: Mem0GatewayConfig | None = None,
    provider_refs: Mem0ProviderRefLookup | None = None,
    clock: Callable[[], float] | None = None,
) -> Mem0AgentMemoryGateway:
    return Mem0AgentMemoryGateway(
        config or _config(),
        provider_refs=provider_refs,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        **({"clock": clock} if clock is not None else {}),
    )
