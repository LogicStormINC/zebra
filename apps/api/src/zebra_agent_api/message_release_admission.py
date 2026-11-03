"""Resolve a release change for a newly accepted durable message."""

from agent_core.contracts.session_commands import MessageReleaseBinding, SessionCommand
from agent_core.domain.agent_definition_snapshots import BindingPurpose
from agent_core.domain.bundle_definition import BundleDefinitionSnapshot
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.runtime_bundle_types import ArtifactPin
from agent_core.ports.agent_registry import AgentRegistryPort
from agent_security.host_grant import VerifiedHostGrant
from agent_storage import ControlPlaneStores
from agent_storage.postgres.task_admission import load_session_task_binding
from zebra_agent_config.settings import ZebraAgentSettings

from zebra_agent_api.publication_consumer import resolve_consumer_binding
from zebra_agent_api.responses import ApiResponse, bad_request
from zebra_agent_api.session_binding import renew_task_binding_snapshot


def prepare_message_release(
    stores: ControlPlaneStores,
    settings: ZebraAgentSettings,
    registry: AgentRegistryPort | None,
    command: SessionCommand,
    events: list[SessionEvent],
    verified: VerifiedHostGrant | None,
) -> MessageReleaseBinding | ApiResponse | None:
    if (
        settings.storage_authority != "postgresql"
        or not settings.publication_management_config
        or command.payload.get("clarification_id") is not None
    ):
        return None
    workspace = stores.workspaces.get_workspace(command.session_id)
    old = workspace.definition_snapshot if workspace is not None else None
    if (
        not isinstance(old, BundleDefinitionSnapshot)
        or old.binding_purpose is not BindingPurpose.PRODUCTION
    ):
        return None
    if verified is None:
        return ApiResponse(403, {"status": "forbidden"})
    effective = resolve_consumer_binding(
        settings,
        registry,
        old.definition_id,
        old.bound_version.runtime_assembly.bundle.manifest.scope.environment,
        verified.context,
        verified,
    )
    if isinstance(effective, ApiResponse):
        return effective
    try:
        old_assembly = old.bound_version.runtime_assembly
        remembered = next(
            (
                ArtifactPin.model_validate(raw).id
                for event in reversed(events)
                if event.event_type is EventType.USER_MESSAGE_RECEIVED
                and (raw := event.payload.get("selected_model_pin")) is not None
            ),
            old_assembly.provider_profile.pin.id,
        )
        requested = command.payload.get("selected_model_id")
        if requested is not None and not isinstance(requested, str):
            return bad_request("selected_model_id must be a string")
        adopted = old.snapshot_for_model_selection(
            effective=effective, selected_model_id=remembered, requested_model_id=requested,
        )
        adopted.bound_version.runtime_assembly.resolve_session_model(
            requested_id=requested, remembered_id=remembered if adopted is old else None
        )
    except ValueError as exc:
        return bad_request(str(exc))
    if adopted is old:
        return None
    namespace = getattr(stores, "deployment_namespace", None)
    if not isinstance(namespace, str):
        return ApiResponse(503, {"status": "message_storage_unavailable"})
    current = load_session_task_binding(
        settings.database_url, deployment_namespace=namespace, session_id=command.session_id
    )
    if current is None:
        return ApiResponse(409, {"status": "host_binding_missing"})
    try:
        binding = renew_task_binding_snapshot(
            current,
            verified.context,
            authority_issuer=verified.authority_issuer,
            release_change=(old.snapshot_digest, adopted.snapshot_digest),
            previous_definition_digest=old.definition_digest,
            verified_subject_ref=verified.subject_ref,
        )
    except ValueError:
        return ApiResponse(409, {"status": "host_binding_revision_conflict"})
    return MessageReleaseBinding(
        previous_snapshot_digest=old.snapshot_digest,
        snapshot=adopted,
        binding=binding,
    )
