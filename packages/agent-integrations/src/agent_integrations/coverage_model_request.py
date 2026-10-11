"""Opt-in prepared Chat transport; durable reservation belongs to its caller."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from time import perf_counter
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from weakref import WeakKeyDictionary

import httpcore
import httpx
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCompletion,
    ModelInvocationPolicy,
    ModelReasoningEffort,
    ModelRole,
    ModelThinkingMode,
    ModelToolChoice,
    ModelToolDefinition,
)
from agent_core.ports.model_gateway import ModelResponseRejectedError

from agent_integrations.deepseek_profiles import (
    ResolvedDeepSeekInvocation,
    _validate_invocation,
    deepseek_profile,
)
from agent_integrations.model_errors import ModelProviderError, normalize_provider_error
from agent_integrations.openai_payloads import parse_completion, provider_tool_names
from agent_integrations.request_metadata import ModelRequestMetadata, _canonical_json

if TYPE_CHECKING:
    from agent_integrations.openai_compatible import OpenAICompatibleModelGateway


@dataclass(frozen=True, eq=False)
class PreparedModelRequest:
    """Inspection only: construction does not grant transport or budget admission.

    Nested frozen values are checked against a private snapshot before transport.
    The business digest is the canonical wire hash, independent of object ownership.
    """

    body: bytes
    endpoint: str
    provider: str
    default_model: str
    resolved: ResolvedDeepSeekInvocation
    request_metadata: ModelRequestMetadata

    @property
    def request_digest(self) -> str:
        return self.request_metadata.request_hash


class PreparedChatRequests:
    def __init__(self) -> None:
        # Weak identity registry releases abandoned preparations and rejects raw copies.
        self._issued: WeakKeyDictionary[PreparedModelRequest, tuple[object, str]] = (
            WeakKeyDictionary()
        )

    def prepare(
        self,
        gateway: OpenAICompatibleModelGateway,
        messages: list[SessionMessage],
        policy: ModelInvocationPolicy,
        *,
        tools: tuple[ModelToolDefinition, ...],
        stream: bool,
        strict_tools: bool,
    ) -> PreparedModelRequest:
        from agent_integrations.openai_compatible import CHAT_COMPLETIONS_PATH

        policy = _validated_policy(policy)
        _configuration(gateway)
        if (
            type(gateway._max_retries) is not int
            or gateway._max_retries != 0
            or tools
            or stream
            or strict_tools
            or policy.role is not ModelRole.REVIEWER
            or policy.tool_choice is not ModelToolChoice.NONE
            or gateway._provider_name.lower() != "deepseek"
            or not messages
        ):
            raise ValueError("prepared Chat requires text-only REVIEWER/NONE and zero retries")
        for message in messages:
            if (
                type(message) is not SessionMessage
                or type(message.role) is not MessageRole
                or message.role not in (MessageRole.SYSTEM, MessageRole.USER, MessageRole.ASSISTANT)
                or not isinstance(message.content, str)
                or message.tool_calls
                or message.tool_call_id is not None
                or message.provider_image_data_urls
            ):
                raise ValueError("prepared Chat does not support tools or images")
        resolved = gateway._resolve_deepseek(policy, has_tools=False)
        if (
            type(resolved) is not ResolvedDeepSeekInvocation
            or _snapshot(resolved.profile)
            != _snapshot(deepseek_profile(resolved.profile.profile_id))
            or resolved.role is not ModelRole.REVIEWER
            or ModelRole.REVIEWER not in resolved.profile.roles
            or resolved.tool_choice is not ModelToolChoice.NONE
            or type(resolved.thinking_mode) is not ModelThinkingMode
            or resolved.thinking_mode is ModelThinkingMode.AUTO
            or (
                resolved.reasoning_effort is not None
                and type(resolved.reasoning_effort) is not ModelReasoningEffort
            )
            or type(resolved.max_output_tokens) is not int
            or not (
                0 < resolved.max_output_tokens <= resolved.profile.context_window.max_output_tokens
            )
        ):
            raise ValueError("unsupported prepared Chat profile")
        _validate_invocation(
            resolved.profile,
            has_tools=False,
            thinking_mode=resolved.thinking_mode,
            reasoning_effort=resolved.reasoning_effort,
            tool_choice=resolved.tool_choice,
        )
        body, metadata = gateway._request_body(
            messages,
            tools=(),
            tool_names=provider_tool_names(()),
            stream=False,
            resolved=resolved,
            strict_tools=False,
        )
        if metadata is None:
            raise ValueError("prepared Chat requires resolved request metadata")
        request = PreparedModelRequest(
            _canonical_json(body),
            f"{gateway._base_url}{CHAT_COMPLETIONS_PATH}",
            gateway._provider_name,
            gateway._model_name,
            deepcopy(resolved),
            deepcopy(metadata),
        )
        self._issued[request] = (_snapshot(request), _configuration(gateway))
        return request

    def send(
        self,
        gateway: OpenAICompatibleModelGateway,
        request: PreparedModelRequest,
    ) -> ModelCompletion:
        if type(request) is not PreparedModelRequest:
            raise ValueError("unissued prepared Chat request")
        evidence = self._issued.get(request)
        if evidence is None:
            raise ValueError("foreign, changed or consumed prepared Chat request")
        frozen = deepcopy(request)
        if evidence != (_snapshot(frozen), _configuration(gateway)):
            raise ValueError("changed prepared Chat request or configuration")
        # Consume before any I/O, including failures: caller must reserve a new attempt.
        if self._issued.pop(request, None) is None:
            raise ValueError("consumed prepared Chat request")
        request = frozen
        started = perf_counter()
        try:
            payload = gateway._post_chat_completion(request.body, endpoint=request.endpoint)
            return parse_completion(
                payload,
                provider_name=request.provider,
                default_model_name=request.default_model,
                latency_ms=int((perf_counter() - started) * 1000),
                retry_count=0,
                resolved=request.resolved,
                request_metadata=request.request_metadata,
                internal_names={},
                tools_advertised=False,
            )
        except ModelResponseRejectedError as error:
            error.retryable = False
            raise
        except Exception as error:
            normalized = normalize_provider_error(error)
            raise ModelProviderError(
                normalized.normalized_error,
                retryable=False,
                retry_count=0,
            ) from error


def _snapshot(value: object) -> object:
    """Typed immutable evidence also detects object.__setattr__ and raw typed copies."""
    kind = type(value)
    if is_dataclass(value) and not isinstance(value, type):
        return kind, _snapshot(vars(value)) if hasattr(value, "__dict__") else tuple(
            (field.name, _snapshot(getattr(value, field.name))) for field in fields(value)
        )
    if isinstance(value, Enum):
        return kind, value.value
    if isinstance(value, dict):
        return kind, frozenset((_snapshot(key), _snapshot(item)) for key, item in value.items())
    if isinstance(value, tuple | list):
        return kind, tuple(_snapshot(item) for item in value)
    if isinstance(value, set | frozenset):
        return kind, frozenset(_snapshot(item) for item in value)
    return kind, value


def _configuration(gateway: OpenAICompatibleModelGateway) -> str:
    try:
        netloc = urlsplit(gateway._base_url).netloc
    except ValueError:
        raise ValueError("unsupported prepared endpoint") from None
    if "@" in netloc:
        raise ValueError("unsupported prepared endpoint")
    router = gateway._deepseek_router
    # Hash only; never keep credentials in prepared values or request metadata.
    configuration = (
        gateway._provider_name,
        gateway._base_url,
        gateway._model_name,
        gateway._api_key,
        gateway._timeout_s,
        gateway._max_retries,
        id(gateway),
        id(gateway._client),
        _prepared_client_configuration(gateway._client) if gateway._client is not None else None,
        id(router),
        _snapshot(router._role_profiles) if router is not None else None,
        router._legacy_executor_model if router is not None else None,
    )
    return hashlib.sha256(repr(configuration).encode()).hexdigest()


def _validated_policy(policy: ModelInvocationPolicy) -> ModelInvocationPolicy:
    if type(policy) is not ModelInvocationPolicy or set(vars(policy)) != {
        field.name for field in fields(ModelInvocationPolicy)
    }:
        raise ValueError("unsupported raw prepared policy shape")
    if (
        type(policy.role) is not ModelRole
        or type(policy.thinking_mode) is not ModelThinkingMode
        or type(policy.tool_choice) is not ModelToolChoice
        or (
            policy.reasoning_effort is not None
            and type(policy.reasoning_effort) is not ModelReasoningEffort
        )
        or (
            policy.max_output_tokens is not None
            and (type(policy.max_output_tokens) is not int or policy.max_output_tokens <= 0)
        )
        or (
            policy.profile_id is not None
            and (type(policy.profile_id) is not str or not policy.profile_id.strip())
        )
    ):
        raise ValueError("unsupported raw prepared policy fields")
    return ModelInvocationPolicy(**vars(policy))


def _prepared_client_configuration(client: httpx.Client) -> str:
    """Fail closed against the installed httpx/httpcore synchronous transport shapes.

    MockTransport is a trusted test seam: its handler is not a network bound proof.
    Custom clients/transports, proxies, hooks, auth flows and query defaults are unsupported.
    ponytail: reused pools are refused; supporting them requires validating cached connections.
    """
    if (
        type(client) is not httpx.Client
        or client.auth is not None
        or type(client.params) is not httpx.QueryParams
        or client.params
        or type(client.event_hooks) is not dict
        or set(client.event_hooks) != {"request", "response"}
        or any(type(hooks) is not list or hooks for hooks in client.event_hooks.values())
        or any(
            name in vars(client)
            for name in dir(httpx.Client)
            if callable(getattr(httpx.Client, name))
        )
        or type(client._mounts) is not dict
        or client._mounts
    ):
        raise ValueError("unsupported prepared httpx client capabilities")
    transport = client._transport
    transport_configuration: object
    if type(transport) is httpx.MockTransport:
        if set(vars(transport)) != {"handler"}:
            raise ValueError("unsupported prepared MockTransport shape")
        transport_configuration = (id(transport), id(transport.handler))
    elif type(transport) is httpx.HTTPTransport:
        pool = transport._pool
        if (
            set(vars(transport)) != {"_pool"}
            or type(pool) is not httpcore.ConnectionPool
            or type(pool._retries) is not int
            or pool._retries != 0
            or type(pool._network_backend) is not httpcore.SyncBackend
            or vars(pool._network_backend)
            or any(
                name in vars(pool)
                for name in dir(httpcore.ConnectionPool)
                if callable(getattr(httpcore.ConnectionPool, name))
            )
            or pool.connections
            or pool._requests
        ):
            raise ValueError(
                "unsupported prepared HTTPTransport: require unused standard zero retries"
            )
        transport_configuration = (
            id(transport),
            id(pool),
            _snapshot(
                {
                    key: value
                    for key, value in vars(pool).items()
                    if key not in {"_connections", "_requests", "_optional_thread_lock"}
                }
            ),
        )
    else:
        raise ValueError("unsupported prepared transport type")
    configuration = (
        transport_configuration,
        client.headers.raw,
        list(client.cookies.jar),
        client.timeout.as_dict(),
        str(client.base_url),
        client.follow_redirects,
        client.max_redirects,
        client.trust_env,
        client._default_encoding,
    )
    return hashlib.sha256(repr(configuration).encode()).hexdigest()


def _build_prepared_http_request(
    client: httpx.Client,
    *,
    endpoint: str,
    headers: dict[str, str],
    body: bytes,
) -> httpx.Request:
    configuration = _prepared_client_configuration(client)
    request = client.build_request("POST", endpoint, headers=headers, content=body)
    if (
        _prepared_client_configuration(client) != configuration
        or str(request.url) != endpoint
        or type(request.stream) is not httpx.ByteStream
        or request.content != body
        or request.headers.get("content-length") != str(len(body))
        or "transfer-encoding" in request.headers
        or "content-encoding" in request.headers
    ):
        raise ValueError("prepared HTTP request differs from frozen wire")
    return request
