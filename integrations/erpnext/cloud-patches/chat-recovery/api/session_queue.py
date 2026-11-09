from __future__ import annotations

import os
from pathlib import Path

from agent_core.application import SessionBootstrapCommand, SessionBootstrapService
from agent_core.application.workspace_projection import rebuild_workspace
from agent_core.domain.agent_definition_snapshots import AgentDefinitionSnapshot
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_core.domain.tool_profiles import ToolProfile
from agent_core.ports.idempotency_store import IdempotencyRecord
from agent_core.ports.task_admission_transaction import (
    TaskAdmissionIdempotencyConflict,
)
from agent_security.host_grant import VerifiedHostGrant
from agent_storage import ControlPlaneStores
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_attachment_persistence import persist_initial_attachments
from zebra_agent_api.session_payloads import CreateSessionPayload, parse_create_session_payload


def create_queued_session(
    stores: ControlPlaneStores,
    parsed: CreateSessionPayload,
    *,
    host_context: HostContextEnvelope | None = None,
    definition_snapshot: AgentDefinitionSnapshot | None = None,
    admission_dsn: str | None = None,
    admission_namespace: str | None = None,
    idempotency_key: str | None = None,
    idempotency_request_hash: str | None = None,
    frozen_manifest_digest: str | None = None,
    verified_host_grant: VerifiedHostGrant | None = None,
    coverage_configuration_digest: str | None = None,
    public_idempotency_key: str | None = None,
) -> ApiResponse:
    if "coverage_admission" in parsed and coverage_configuration_digest is None:
        preflight = parse_create_session_payload(dict(parsed))
        if isinstance(preflight, ApiResponse):
            return preflight
    if admission_dsn and host_context is not None:
        if (
            not isinstance(verified_host_grant, VerifiedHostGrant)
            or verified_host_grant.context != host_context
        ):
            return ApiResponse(403, {"status": "verified_host_grant_required"})
    bootstrap = SessionBootstrapService().build(
        SessionBootstrapCommand(
            title=str(parsed["title"]),
            user_input=str(parsed["prompt"]),
            workspace_root=_workspace_root(str(parsed["workspace"])),
            policy_profile=str(parsed["policy_profile"]),
            tool_profile=ToolProfile(str(parsed["tool_profile"])),
            network_profile=str(parsed["network_profile"]),
            network_allowlist=tuple(parsed["network_allowlist"]),
            mcp_allowlist=tuple(parsed["mcp_allowlist"]),
            skill_components=tuple(parsed["skill_components"]),
            history_session_ids=parsed["history_session_ids"],
            max_model_calls=parsed["max_model_calls"],
            max_tool_calls=parsed["max_tool_calls"],
            host_context=host_context,
            definition_snapshot=definition_snapshot,
            interaction_mode=parsed["interaction_mode"],
            model_profile=parsed["model_profile"],
            reasoning_effort=parsed["reasoning_effort"],
            coverage_admission=parsed.get("coverage_admission"),
        )
    )
    events, attachment_refs = persist_initial_attachments(
        stores.artifact_payloads,
        tuple(bootstrap.events),
        parsed["attachments"],
    )
    workspace = rebuild_workspace(list(events))
    response = ApiResponse(
        status_code=201,
        body={
            "session_id": str(bootstrap.session.session_id),
            "title": str(parsed["title"]),
            "prompt": str(parsed["prompt"]),
            "workspace": str(parsed["workspace"]),
            "executed": False,
            "status": bootstrap.session.status.value,
            "current_sequence": bootstrap.session.current_sequence,
            "tool_profile": str(parsed["tool_profile"]),
            "max_model_calls": parsed["max_model_calls"],
            "max_tool_calls": parsed["max_tool_calls"],
            "network_profile": str(parsed["network_profile"]),
            "network_allowlist": parsed["network_allowlist"],
            "mcp_allowlist": parsed["mcp_allowlist"],
            "skill_components": parsed["skill_components"],
            "mcp_resource_ids": parsed["mcp_resource_ids"],
            "model_profile": parsed["model_profile"],
            "reasoning_effort": parsed["reasoning_effort"],
            **(
                {"history_session_ids": list(parsed["history_session_ids"])}
                if parsed["history_session_ids"] is not None
                else {}
            ),
            **(
                {"mcp_prompt_id": parsed["mcp_prompt_id"]}
                if parsed["mcp_prompt_id"] is not None
                else {}
            ),
            "attachments": [ref.to_mapping() for ref in attachment_refs],
        },
    )
    response.body["idempotency_key"] = idempotency_key
    if coverage_configuration_digest is not None:
        from zebra_agent_api.coverage_http_admission import initial_run

        command_event, command_body = initial_run(bootstrap, idempotency_key)
        events = (*events, command_event)
        response.body.update(status="queued", executed=False, command=command_body)
        response.body["idempotency_key"] = public_idempotency_key
    if admission_dsn and admission_namespace:
        # Phase F3: cloud admission uses the atomic v25 transaction —
        # events, projections, task index, binding and the FULL idempotency
        # response persist or roll back together. The canonical request
        # hash is computed once by the API layer and reused verbatim, so
        # replay and admission can never disagree.
        from datetime import UTC as _UTC
        from datetime import datetime as _dt

        from agent_core.ports.task_admission_transaction import (
            TaskAdmissionRequest,
        )
        from agent_storage.postgres.task_admission import (
            PostgresTaskAdmissionTransaction,
        )

        mode = os.environ.get("ZEBRA_ERPNEXT_CHAT_READONLY", "disabled")
        if mode not in {"enabled", "disabled"}:
            raise ValueError("invalid ERP readonly chat mode")
        require_connector = (
            mode == "enabled" and admission_namespace == "erpnext" and host_context is not None
        )
        profile, frozen = _resolve_host_connector(
            admission_dsn,
            admission_namespace,
            host_context,
            frozen_manifest_digest,
            required=require_connector,
        )
        raw_binding = _derive_binding(
            bootstrap.session.session_id,
            host_context=host_context,
            definition_snapshot=definition_snapshot,
            deployment_namespace=admission_namespace,
            frozen_manifest_digest=frozen_manifest_digest,
            verified_host_grant=verified_host_grant,
            resolved_connector_profile=profile,
            frozen_host_manifest=frozen,
            require_resolved_connector=require_connector,
        )
        idempotency_record = None
        if idempotency_key is not None and idempotency_request_hash is not None:
            idempotency_record = IdempotencyRecord(
                action="session.create",
                idempotency_key=idempotency_key,
                request_hash=idempotency_request_hash,
                status_code=response.status_code,
                response_body=response.body,
                created_at=_dt.now(_UTC),
            )
        try:
            request = TaskAdmissionRequest(
                events=tuple(events),
                session=bootstrap.session,
                workspace=workspace,
                binding=raw_binding if isinstance(raw_binding, TaskBindingSnapshot) else None,
                idempotency=idempotency_record,
            )
            if coverage_configuration_digest is not None:
                from agent_storage.postgres.command_coverage_admission import admit_coverage_task

                receipt = admit_coverage_task(
                    admission_dsn,
                    admission_namespace,
                    request,
                    coverage_configuration_digest,
                )
            else:
                receipt = PostgresTaskAdmissionTransaction(
                    admission_dsn, deployment_namespace=admission_namespace
                ).admit(request)
        except TaskAdmissionIdempotencyConflict:
            return ApiResponse(
                status_code=409,
                body={
                    "status": "idempotency_conflict",
                    "reason": "idempotency key reused with different request",
                },
            )
        if receipt.idempotent_replay and receipt.replayed_record is not None:
            return ApiResponse(
                receipt.replayed_record.status_code,
                receipt.replayed_record.response_body,
            )
        return response
    for event in events:
        stores.events.append(event)
    stores.sessions.save_session(bootstrap.session)
    stores.workspaces.save_workspace(workspace)
    stores.tasks.ensure_for_session(bootstrap.session.session_id)
    return response


def _workspace_root(reference: str) -> Path:
    """Control-plane references keep their uri shape; plain paths resolve."""
    if reference.startswith("workspace://"):
        return Path(reference)
    return Path(reference).expanduser().resolve()


def _derive_binding(
    session_id: object,
    *,
    host_context: HostContextEnvelope | None,
    definition_snapshot: AgentDefinitionSnapshot | None,
    deployment_namespace: str = "zebra",
    frozen_manifest_digest: str | None = None,
    verified_host_grant: VerifiedHostGrant | None = None,
    resolved_connector_profile: object | None = None,
    frozen_host_manifest: object | None = None,
    require_resolved_connector: bool = False,
) -> object:
    """Derive the TaskBindingSnapshot for atomic admission (F3).

    Every cloud admission freezes a binding: Host-bound sessions pin the
    Host grant; internal sessions pin the deployment authority.
    """

    from zebra_agent_api.session_binding import _build_binding_snapshot

    return _build_binding_snapshot(
        session_id,
        host_context=host_context,
        definition_snapshot_digest=(
            definition_snapshot.definition_digest if definition_snapshot else None
        ),
        deployment_namespace=deployment_namespace,
        frozen_manifest_digest=frozen_manifest_digest,
        verified_host_grant=verified_host_grant,
        resolved_connector_profile=resolved_connector_profile,
        frozen_host_manifest=frozen_host_manifest,
        require_resolved_connector=require_resolved_connector,
    )


def _resolve_host_connector(dsn, namespace, host_context, frozen_digest, *, required=False):
    """Read the already frozen immutable profile; atomic admission persists it once."""
    if not required or host_context is None:
        return None, None
    from agent_core.domain.host_connectors import accepts_new_tasks
    from agent_integrations.host_tools import HostToolManifest
    from agent_storage.postgres.host_connectors import PostgresHostConnectorRegistry
    from agent_storage.postgres.host_manifest_freeze import load_frozen_manifest

    registry = PostgresHostConnectorRegistry(dsn, deployment_namespace=namespace)
    binding = registry.resolve_binding(host_context.host_app_id, host_context.namespace_id)
    if binding is None:
        if required or frozen_digest is not None:
            raise ValueError("published Host connector binding is required")
        return None, None
    profile = registry.get_profile(
        binding.host_app_id, binding.connector_id, binding.profile_revision
    )
    if profile is None or not binding.active or not accepts_new_tasks(profile.status):
        raise ValueError("published Host connector profile is unavailable")
    frozen = load_frozen_manifest(
        dsn,
        deployment_namespace=namespace,
        connector_id=profile.connector_id,
        profile_revision=profile.profile_revision,
    )
    if frozen is None:
        raise ValueError("admission frozen Host manifest is unavailable")
    manifest = HostToolManifest.from_payload(frozen)
    if (
        manifest.digest != frozen_digest
        or manifest.workload_identity != profile.workload_identity_ref
    ):
        raise ValueError("admission Host connector manifest drifted")
    return profile, manifest
