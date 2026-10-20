"""Explicit Trench compatibility: historical scope and subscription semantics."""

from zebra_host_grant_broker.grant_minting import ExchangeRequest, GrantMintError
from zebra_host_grant_broker.trench_session import TrenchViewer, parse_agent_scopes


def authorize_legacy(request: ExchangeRequest, viewer: object) -> None:
    if not isinstance(viewer, TrenchViewer):
        raise GrantMintError("legacy_identity_invalid")
    if viewer.allowed_scopes is None:
        # Legacy Hosts retain base capabilities, never implicit extension management.
        if any(scope.startswith("extensions.") for scope in request.scopes):
            raise GrantMintError("viewer_scope_not_allowed")
    elif not set(request.scopes).issubset(viewer.allowed_scopes):
        raise GrantMintError("viewer_scope_not_allowed")
    allowed_types = {
        "trench.source",
        "trench.event",
        "trench.entity",
        "trench.topic",
        "trench.history",
    }
    if any(kind not in allowed_types for kind, _ in request.resource_refs):
        raise GrantMintError("resource_refs_invalid")
    requested_sources = {
        resource_id
        for resource_type, resource_id in request.resource_refs
        if resource_type == "trench.source"
    }
    if requested_sources - viewer.active_source_ids:
        raise GrantMintError("source_not_allowed")
    requested_history = {
        resource_id
        for resource_type, resource_id in request.resource_refs
        if resource_type == "trench.history"
    }
    if requested_history - {viewer.user_id}:
        raise GrantMintError("history_not_allowed")
    if request.resource_refs and not requested_sources and not requested_history:
        raise GrantMintError("source_binding_required")
    required_scopes = {
        "trench.event": "event.read",
        "trench.entity": "entity.read",
        "trench.topic": "topic.read",
        "trench.source": "source.read",
        "trench.history": "history.read",
    }
    for resource_type, _resource_id in request.resource_refs:
        required_scope = required_scopes.get(resource_type)
        if required_scope is not None and required_scope not in request.scopes:
            raise GrantMintError("resource_scope_missing")


def legacy_workload_viewer(principal: dict[str, object]) -> TrenchViewer:
    """Legacy signed claims remain the authority only in explicit compatibility mode."""
    from zebra_host_grant_broker.workload_auth import WorkloadAuthError, _text

    try:
        allowed_scopes = (
            parse_agent_scopes(principal["agentScopes"]) if "agentScopes" in principal else None
        )
    except ValueError as exc:
        raise WorkloadAuthError("workload_agent_scopes_invalid") from exc
    user_id = _text(principal.get("userId"), "workload_principal_invalid")
    workspace_id = _text(principal.get("workspaceId"), "workload_workspace_invalid")
    raw_sources = principal.get("activeSourceIds", [])
    if not isinstance(raw_sources, list) or len(raw_sources) > 4096:
        raise WorkloadAuthError("workload_sources_invalid")
    sources = frozenset(_text(value, "workload_sources_invalid") for value in raw_sources)
    return TrenchViewer(
        user_id=user_id,
        workspace_id=workspace_id,
        active_source_ids=sources,
        allowed_scopes=allowed_scopes,
    )
