from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from agent_core.domain.identifiers import MemoryId
from agent_core.ports.agent_memory_gateway import (
    ConfirmedMemoryPublication,
    MemoryGatewayDeleteRequest,
    MemoryGatewayMutationResult,
    MemoryGatewaySearchRequest,
    MemoryGatewaySearchResult,
    MemoryGatewayStatus,
)

from agent_integrations.mem0.circuit import Mem0CircuitBreaker
from agent_integrations.mem0.config import Mem0GatewayConfig
from agent_integrations.mem0.responses import (
    provider_ref,
    published_provider_ref,
    search_hits,
)

MAX_RESPONSE_BYTES = 4 * 1_024 * 1_024


class Mem0ProviderRefLookup(Protocol):
    """Read boundary implemented later by the durable delivery ledger."""

    def resolve(self, *, memory_id: MemoryId, namespace: str) -> str | None: ...


@dataclass(frozen=True, slots=True)
class _CallResult:
    status_code: int | None = None
    payload: object = None
    failure: str | None = None


class Mem0AgentMemoryGateway:
    def __init__(
        self,
        config: Mem0GatewayConfig,
        *,
        provider_refs: Mem0ProviderRefLookup | None = None,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._provider_refs = provider_refs
        self._client = client
        self._circuit = Mem0CircuitBreaker(
            failure_threshold=config.circuit_failure_threshold,
            recovery_seconds=config.circuit_recovery_seconds,
            clock=clock,
        )

    def publish(
        self,
        publication: ConfirmedMemoryPublication,
    ) -> MemoryGatewayMutationResult:
        if not self._config.enabled:
            return _mutation(MemoryGatewayStatus.DISABLED, "mem0_disabled")

        result = self._call(
            "POST",
            "/memories",
            {
                "messages": [{"role": "user", "content": publication.text}],
                "user_id": encode_mem0_namespace(publication.namespace),
                "metadata": {
                    "zebra_memory_id": str(publication.memory_id),
                    "zebra_idempotency_key": publication.idempotency_key,
                    "zebra_schema_version": 1,
                },
                "infer": False,
            },
        )
        if result.failure is not None:
            return _mutation(MemoryGatewayStatus.DEGRADED, result.failure)
        if result.status_code is None or not 200 <= result.status_code < 300:
            self._circuit.record_success()
            return _mutation(MemoryGatewayStatus.DEGRADED, "request_rejected")

        published_ref = published_provider_ref(result.payload)
        if published_ref is None:
            self._circuit.record_failure()
            return _mutation(MemoryGatewayStatus.DEGRADED, "invalid_response")
        self._circuit.record_success()
        return MemoryGatewayMutationResult(
            status=MemoryGatewayStatus.SUCCEEDED,
            provider_ref=published_ref,
        )

    def search(self, request: MemoryGatewaySearchRequest) -> MemoryGatewaySearchResult:
        if not self._config.enabled:
            return MemoryGatewaySearchResult(
                status=MemoryGatewayStatus.DISABLED,
                detail="mem0_disabled",
            )

        encoded_namespace = encode_mem0_namespace(request.namespace)
        result = self._call(
            "POST",
            "/search",
            {
                "query": request.query,
                "filters": {"user_id": encoded_namespace},
                "top_k": request.limit,
            },
        )
        if result.failure is not None:
            return _search_failure(result.failure)
        if result.status_code is None or not 200 <= result.status_code < 300:
            self._circuit.record_success()
            return _search_failure("request_rejected")

        hits, invalid_count, excess_count = search_hits(
            result.payload,
            encoded_namespace,
            limit=request.limit,
        )
        if hits is None:
            self._circuit.record_failure()
            return _search_failure("invalid_response")
        if not hits and invalid_count:
            self._circuit.record_failure()
            return _search_failure("invalid_response")
        detail_parts = []
        if invalid_count:
            detail_parts.append(f"discarded_invalid_hits={invalid_count}")
        if excess_count:
            detail_parts.append(f"discarded_excess_hits={excess_count}")
        self._circuit.record_success()
        return MemoryGatewaySearchResult(
            status=(
                MemoryGatewayStatus.PARTIAL
                if invalid_count or excess_count
                else MemoryGatewayStatus.SUCCEEDED
            ),
            hits=hits,
            detail=";".join(detail_parts) or None,
        )

    def delete(self, request: MemoryGatewayDeleteRequest) -> MemoryGatewayMutationResult:
        if not self._config.enabled:
            return _mutation(MemoryGatewayStatus.DISABLED, "mem0_disabled")
        if self._provider_refs is None:
            return _mutation(MemoryGatewayStatus.DEGRADED, "provider_ref_lookup_unavailable")
        try:
            lookup_ref = self._provider_refs.resolve(
                memory_id=request.memory_id,
                namespace=request.namespace,
            )
        except Exception:
            return _mutation(MemoryGatewayStatus.DEGRADED, "provider_ref_lookup_unavailable")
        if lookup_ref is None:
            return _mutation(MemoryGatewayStatus.NOT_FOUND, "provider_ref_not_found")
        resolved_ref = provider_ref(lookup_ref)
        if resolved_ref is None:
            return _mutation(MemoryGatewayStatus.DEGRADED, "invalid_provider_ref")

        result = self._call("DELETE", f"/memories/{resolved_ref}")
        if result.failure is not None:
            return _mutation(MemoryGatewayStatus.DEGRADED, result.failure)
        if result.status_code == 404:
            self._circuit.record_success()
            return _mutation(MemoryGatewayStatus.NOT_FOUND, "provider_memory_not_found")
        if result.status_code is None or not 200 <= result.status_code < 300:
            self._circuit.record_success()
            return _mutation(MemoryGatewayStatus.DEGRADED, "request_rejected")
        self._circuit.record_success()
        return MemoryGatewayMutationResult(
            status=MemoryGatewayStatus.SUCCEEDED,
            provider_ref=resolved_ref,
        )

    def _call(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> _CallResult:
        if not self._circuit.allows_request():
            return _CallResult(failure="circuit_open")
        try:
            stream = (
                self._client.stream(
                    method,
                    self._config.base_url + path,
                    headers={"X-API-Key": self._config.api_key},
                    json=payload,
                    timeout=self._config.timeout_seconds,
                )
                if self._client is not None
                else httpx.stream(
                    method,
                    self._config.base_url + path,
                    headers={"X-API-Key": self._config.api_key},
                    json=payload,
                    timeout=self._config.timeout_seconds,
                    trust_env=self._config.trust_environment_proxy,
                )
            )
            with stream as response:
                if response.status_code == 429:
                    self._circuit.record_failure()
                    return _CallResult(status_code=429, failure="rate_limited")
                if response.status_code >= 500:
                    self._circuit.record_failure()
                    return _CallResult(
                        status_code=response.status_code,
                        failure="provider_unavailable",
                    )
                if not 200 <= response.status_code < 300:
                    return _CallResult(status_code=response.status_code)

                content = bytearray()
                for chunk in response.iter_bytes():
                    if len(content) + len(chunk) > MAX_RESPONSE_BYTES:
                        self._circuit.record_failure()
                        return _CallResult(
                            status_code=response.status_code,
                            failure="response_too_large",
                        )
                    content.extend(chunk)
        except httpx.TimeoutException:
            self._circuit.record_failure()
            return _CallResult(failure="provider_timeout")
        except httpx.HTTPError:
            self._circuit.record_failure()
            return _CallResult(failure="provider_unavailable")

        try:
            response_payload = json.loads(content) if content else None
        except ValueError:
            self._circuit.record_failure()
            return _CallResult(status_code=response.status_code, failure="invalid_response")
        return _CallResult(status_code=response.status_code, payload=response_payload)


def encode_mem0_namespace(namespace: str) -> str:
    return "zebra:" + hashlib.sha256(namespace.encode("utf-8")).hexdigest()


def _mutation(status: MemoryGatewayStatus, detail: str) -> MemoryGatewayMutationResult:
    return MemoryGatewayMutationResult(status=status, detail=detail)


def _search_failure(detail: str) -> MemoryGatewaySearchResult:
    return MemoryGatewaySearchResult(status=MemoryGatewayStatus.DEGRADED, detail=detail)
