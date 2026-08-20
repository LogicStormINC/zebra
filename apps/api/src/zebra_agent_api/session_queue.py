from __future__ import annotations

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
from agent_storage import ControlPlaneStores

from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.session_attachment_persistence import persist_initial_attachments
from zebra_agent_api.session_payloads import CreateSessionPayload


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
) -> ApiResponse:
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
            history_session_ids=parsed["history_session_ids"],
            max_model_calls=parsed["max_model_calls"],
            max_tool_calls=parsed["max_tool_calls"],
            host_context=host_context,
            definition_snapshot=definition_snapshot,
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
            "tool_profile": str(parsed["tool_profile"]),
            "max_model_calls": parsed["max_model_calls"],
            "max_tool_calls": parsed["max_tool_calls"],
            "network_profile": str(parsed["network_profile"]),
            "network_allowlist": parsed["network_allowlist"],
            "mcp_allowlist": parsed["mcp_allowlist"],
            "mcp_resource_ids": parsed["mcp_resource_ids"],
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

        raw_binding = _derive_binding(
            bootstrap.session.session_id,
            host_context=host_context,
            definition_snapshot=definition_snapshot,
            deployment_namespace=admission_namespace,
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
            receipt = PostgresTaskAdmissionTransaction(
                admission_dsn, deployment_namespace=admission_namespace
            ).admit(
                TaskAdmissionRequest(
                    events=tuple(events),
                    session=bootstrap.session,
                    workspace=workspace,
                    binding=raw_binding if isinstance(raw_binding, TaskBindingSnapshot) else None,
                    idempotency=idempotency_record,
                )
            )
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
    )
