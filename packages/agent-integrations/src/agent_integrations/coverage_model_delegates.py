"""Exact builtin MODEL delegate provenance; no provider-origin claim."""

from types import FunctionType
from weakref import ReferenceType, WeakKeyDictionary

from agent_integrations.coverage_model_request import PreparedChatRequests, PreparedModelRequest
from agent_integrations.deepseek_profiles import DeepSeekProfileRouter
from agent_integrations.openai_compatible import OpenAICompatibleModelGateway

_NATIVE_REMOVE = vars(WeakKeyDictionary[object, object]())["_remove"]


def _validate_gateway_delegates(
    gateway: OpenAICompatibleModelGateway, request: PreparedModelRequest | None = None
) -> None:
    """Require builtin callable provenance, not proof of network/provider origin."""

    def builtin(value: object, expected: type[object]) -> None:
        if type(value) is not expected or any(
            name in vars(value) for name in dir(expected) if callable(getattr(expected, name))
        ):
            raise ValueError("strict MODEL requires builtin unmodified gateway delegates")

    # Inspect parents before accessing their children; a foreign dispatcher may
    # also replace prepare/send or the registry's get/pop delegated call paths.
    builtin(gateway, OpenAICompatibleModelGateway)
    builtin(gateway._prepared_requests, PreparedChatRequests)
    builtin(gateway._prepared_requests._issued, WeakKeyDictionary)
    builtin(gateway._deepseek_router, DeepSeekProfileRouter)
    if (
        type(vars(gateway._prepared_requests._issued)["data"]) is not dict
        or type(vars(gateway._deepseek_router)["_role_profiles"]) is not dict
    ):
        raise ValueError("strict MODEL requires builtin delegate dictionaries")
    registry = gateway._prepared_requests._issued
    state = vars(registry)
    remove = state["_remove"]
    if (
        set(state) != {"data", "_remove", "_pending_removals", "_iterating", "_dirty_len"}
        or type(state["_pending_removals"]) is not list
        or state["_pending_removals"]
        or type(state["_iterating"]) is not set
        or state["_iterating"]
        or type(state["_dirty_len"]) is not bool
        or type(remove) is not FunctionType
        or remove.__code__ is not _NATIVE_REMOVE.__code__
        or remove.__globals__ is not _NATIVE_REMOVE.__globals__
        or remove.__closure__ is not None
        or remove.__kwdefaults__ is not None
        or vars(remove)
        or type(remove.__defaults__) is not tuple
        or len(remove.__defaults__) != 1
        or type(remove.__defaults__[0]) is not ReferenceType
        or remove.__defaults__[0].__callback__ is not None
        or remove.__defaults__[0]() is not registry
        or len(state["data"]) != (0 if request is None else 1)
        or any(
            type(key) is not ReferenceType or key() is not request or key.__callback__ is not remove
            for key in state["data"]
        )
    ):
        raise ValueError("strict MODEL requires native idle registry callback/state")
