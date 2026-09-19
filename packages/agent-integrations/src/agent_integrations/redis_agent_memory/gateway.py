from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from agent_core.domain.identifiers import MemoryId
from agent_core.domain.memory_delivery import MemoryDeliveryCertainty
from agent_core.ports.agent_memory_gateway import (
    ConfirmedMemoryPublication,
    MemoryGatewayDeleteRequest,
    MemoryGatewayHit,
    MemoryGatewayMutationResult,
    MemoryGatewaySearchRequest,
    MemoryGatewaySearchResult,
    MemoryGatewayStatus,
)

from agent_integrations.redis_agent_memory.config import RedisAgentMemoryConfig

MAX_RESPONSE_BYTES = 4 * 1_024 * 1_024


@dataclass(frozen=True, slots=True)
class _HttpResult:
    status_code: int | None = None
    payload: object = None
    failure: str | None = None

    @property
    def uncertain(self) -> bool:
        return self.failure is not None or (
            self.status_code is not None and self.status_code >= 500
        )


class RedisAgentMemoryGateway:
    """Provider adapter that keeps Zebra IDs deterministic and recoverable."""

    def __init__(
        self,
        config: RedisAgentMemoryConfig,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._config = config
        self._client = client

    def publish(
        self,
        publication: ConfirmedMemoryPublication,
    ) -> MemoryGatewayMutationResult:
        if not self._config.enabled:
            return _mutation(MemoryGatewayStatus.DISABLED, "redis_agent_memory_disabled")
        memory_id = str(publication.memory_id)
        owner_id = encode_owner_id(publication.namespace)
        existing = self._get(memory_id)
        if existing.failure is not None:
            return _unknown(existing.failure)
        if existing.status_code == 200:
            if not _record_in_scope(existing.payload, memory_id, owner_id):
                return _no_effect("memory_id_scope_collision")
            if _record_text(existing.payload) == publication.text:
                return _applied(memory_id, "replayed")
            return self._update(memory_id, owner_id, publication.text)
        if existing.status_code != 404:
            return _unknown(existing.failure or "provider_read_unavailable")

        result = self._call(
            "POST",
            self._collection_path,
            {"memories": [{"id": memory_id, "text": publication.text, "ownerId": owner_id}]},
        )
        if result.status_code == 201 and _id_in_list(result.payload, "created", memory_id):
            return _applied(memory_id)
        return self._reconcile_publish(
            memory_id,
            owner_id,
            publication.text,
            original=result,
        )

    def search(self, request: MemoryGatewaySearchRequest) -> MemoryGatewaySearchResult:
        if not self._config.enabled:
            return MemoryGatewaySearchResult(
                status=MemoryGatewayStatus.DISABLED,
                detail="redis_agent_memory_disabled",
            )
        owner_id = encode_owner_id(request.namespace)
        result = self._call(
            "POST",
            f"{self._collection_path}/search",
            {
                "text": request.query,
                "filter": {"ownerId": {"eq": owner_id}},
                "limit": request.limit,
            },
        )
        if result.status_code != 200:
            return MemoryGatewaySearchResult(
                status=MemoryGatewayStatus.DEGRADED,
                detail=result.failure or "request_rejected",
            )
        payload = result.payload
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return MemoryGatewaySearchResult(
                status=MemoryGatewayStatus.DEGRADED,
                detail="invalid_response",
            )
        hits: list[MemoryGatewayHit] = []
        invalid = 0
        for item in items[: request.limit]:
            if not isinstance(item, dict) or item.get("ownerId") != owner_id:
                invalid += 1
                continue
            try:
                memory_id = MemoryId(UUID(str(item.get("id"))))
            except (TypeError, ValueError):
                invalid += 1
                continue
            hits.append(MemoryGatewayHit(memory_id=memory_id, provider_ref=str(memory_id)))
        if items and not hits:
            return MemoryGatewaySearchResult(
                status=MemoryGatewayStatus.DEGRADED,
                detail="invalid_response",
            )
        return MemoryGatewaySearchResult(
            status=(MemoryGatewayStatus.PARTIAL if invalid else MemoryGatewayStatus.SUCCEEDED),
            hits=tuple(hits),
            detail=f"discarded_invalid_hits={invalid}" if invalid else None,
        )

    def delete(self, request: MemoryGatewayDeleteRequest) -> MemoryGatewayMutationResult:
        if not self._config.enabled:
            return _mutation(MemoryGatewayStatus.DISABLED, "redis_agent_memory_disabled")
        memory_id = str(request.memory_id)
        owner_id = encode_owner_id(request.namespace)
        existing = self._get(memory_id)
        if existing.failure is not None:
            return _unknown(existing.failure)
        if existing.status_code == 404:
            return _mutation(MemoryGatewayStatus.NOT_FOUND, "provider_memory_not_found")
        if existing.status_code != 200:
            return _unknown(existing.failure or "provider_read_unavailable")
        if not _record_in_scope(existing.payload, memory_id, owner_id):
            return _no_effect("memory_id_scope_collision")
        result = self._call(
            "DELETE",
            self._collection_path,
            {"memoryIds": [memory_id]},
        )
        if result.status_code == 200 and _id_in_list(result.payload, "deleted", memory_id):
            return _applied(memory_id)
        reconciled = self._get(memory_id)
        if reconciled.status_code == 404:
            return _applied(memory_id, "reconciled_after_delete")
        if result.uncertain or reconciled.status_code != 200:
            return _unknown(result.failure or "delete_result_unknown")
        return _no_effect("request_rejected")

    def _update(self, memory_id: str, owner_id: str, text: str) -> MemoryGatewayMutationResult:
        result = self._call(
            "PATCH",
            f"{self._collection_path}/{quote(memory_id, safe='')}",
            {"text": text, "ownerId": owner_id},
        )
        if result.status_code == 200 and _record_matches(result.payload, memory_id, owner_id, text):
            return _applied(memory_id)
        return self._reconcile_publish(memory_id, owner_id, text, original=result)

    def _reconcile_publish(
        self,
        memory_id: str,
        owner_id: str,
        text: str,
        *,
        original: _HttpResult,
    ) -> MemoryGatewayMutationResult:
        reconciled = self._get(memory_id)
        if reconciled.status_code == 200:
            if _record_matches(reconciled.payload, memory_id, owner_id, text):
                return _applied(memory_id, "reconciled_after_response_loss")
            return _no_effect("memory_id_scope_or_content_conflict")
        if not original.uncertain and reconciled.status_code == 404:
            return _no_effect("request_rejected")
        return _unknown(original.failure or "publish_result_unknown")

    def _get(self, memory_id: str) -> _HttpResult:
        return self._call("GET", f"{self._collection_path}/{quote(memory_id, safe='')}")

    @property
    def _collection_path(self) -> str:
        return f"/v1/stores/{quote(self._config.store_id, safe='')}/long-term-memory"

    def _call(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> _HttpResult:
        headers = {"Authorization": f"Bearer {self._config.api_key}"}
        try:
            stream = (
                self._client.stream(
                    method,
                    self._config.base_url + path,
                    headers=headers,
                    json=payload,
                    timeout=self._config.timeout_seconds,
                )
                if self._client is not None
                else httpx.stream(
                    method,
                    self._config.base_url + path,
                    headers=headers,
                    json=payload,
                    timeout=self._config.timeout_seconds,
                    trust_env=self._config.trust_environment_proxy,
                )
            )
            with stream as response:
                content = bytearray()
                for chunk in response.iter_bytes():
                    if len(content) + len(chunk) > MAX_RESPONSE_BYTES:
                        return _HttpResult(response.status_code, failure="response_too_large")
                    content.extend(chunk)
        except httpx.TimeoutException:
            return _HttpResult(failure="provider_timeout")
        except httpx.HTTPError:
            return _HttpResult(failure="provider_unavailable")
        try:
            response_payload = json.loads(content) if content else None
        except ValueError:
            return _HttpResult(response.status_code, failure="invalid_response")
        failure = None
        if response.status_code == 429:
            failure = "rate_limited"
        elif response.status_code >= 500:
            failure = "provider_unavailable"
        return _HttpResult(response.status_code, response_payload, failure)


def encode_owner_id(namespace: str) -> str:
    return "z-" + hashlib.sha256(namespace.encode("utf-8")).hexdigest()[:62]


def _record_in_scope(payload: object, memory_id: str, owner_id: str) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("id") == memory_id
        and payload.get("ownerId") == owner_id
    )


def _record_text(payload: object) -> str | None:
    text = payload.get("text") if isinstance(payload, dict) else None
    return text if isinstance(text, str) else None


def _record_matches(payload: object, memory_id: str, owner_id: str, text: str) -> bool:
    return _record_in_scope(payload, memory_id, owner_id) and _record_text(payload) == text


def _id_in_list(payload: object, field: str, memory_id: str) -> bool:
    values = payload.get(field) if isinstance(payload, dict) else None
    return isinstance(values, list) and memory_id in values


def _applied(provider_ref: str, detail: str | None = None) -> MemoryGatewayMutationResult:
    return MemoryGatewayMutationResult(
        status=MemoryGatewayStatus.SUCCEEDED,
        provider_ref=provider_ref,
        detail=detail,
    )


def _no_effect(detail: str) -> MemoryGatewayMutationResult:
    return MemoryGatewayMutationResult(
        status=MemoryGatewayStatus.DEGRADED,
        certainty=MemoryDeliveryCertainty.DEFINITE_NO_EFFECT,
        detail=detail,
    )


def _unknown(detail: str) -> MemoryGatewayMutationResult:
    return MemoryGatewayMutationResult(
        status=MemoryGatewayStatus.DEGRADED,
        certainty=MemoryDeliveryCertainty.UNKNOWN,
        detail=detail,
    )


def _mutation(status: MemoryGatewayStatus, detail: str) -> MemoryGatewayMutationResult:
    return MemoryGatewayMutationResult(status=status, detail=detail)
