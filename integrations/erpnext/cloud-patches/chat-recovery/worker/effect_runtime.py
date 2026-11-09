"""Worker composition for local and cloud Effect payload strategies."""

from collections.abc import Callable
from typing import Any

import zebra_agent_worker.session_handoff as handoff
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import WorkerLease
from agent_core.ports import ArtifactPayloadStorePort, EffectDispatchPort, EffectLedgerPort
from agent_tools import EffectGuardedToolGateway, FencedEffectToolGateway
from zebra_agent_worker import cloud_effect_payloads
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.tool_output_artifacts import CloudToolOutputArtifactCoordinator


def guard_worker_effects(
    gateway: Any,
    *,
    ledger: EffectLedgerPort | None,
    session_id: SessionId,
    recovered_handoff: handoff.RecoveredHandoff | None,
    authority_scope: str,
    dispatch: EffectDispatchPort | None,
    local_artifacts: ArtifactPayloadStorePort | None,
    lease: WorkerLease,
    recorders: list[DurableHarnessEventRecorder],
    ownership_check: Callable[[], None],
    cloud_artifacts: CloudToolOutputArtifactCoordinator | None,
) -> EffectGuardedToolGateway | FencedEffectToolGateway:
    from agent_storage.postgres.erp_chat_readonly import (
        TOOLS,
        allowed_tools,
    )
    from agent_storage.postgres.erp_chat_readonly import (
        enabled as chat_enabled,
    )
    from agent_tools.effect_guard_support import read_only_tool_names

    payloadless_readonly = chat_enabled()
    shown = (
        frozenset(tool.name for tool in gateway.model_tools)
        if payloadless_readonly
        else frozenset()
    )
    if payloadless_readonly and (
        not TOOLS <= shown <= allowed_tools()
        or not shown <= read_only_tool_names(gateway)
        or gateway.effective_mcp_tools
        or gateway.effective_skill_components
    ):
        raise ValueError("ERP chat requires its approved readonly tool surface")
    # ponytail: zero-Artifact chat still uses the native ownership/Fresh/fenced path;
    # any effectful capability requires the normal durable payload strategy.
    effect_payloads = cloud_effect_payloads.build_cloud_effect_payloads(
        session_id, cloud_artifacts, dispatch
    )
    return handoff.guard_effectful_tools(
        gateway,
        ledger=ledger,
        session_id=session_id,
        recovered_handoff=recovered_handoff,
        authority_scope=authority_scope,
        dispatch=dispatch,
        artifacts=None if effect_payloads is not None else local_artifacts,
        fence=lease.fence,
        claim_ttl=lease.expires_at - lease.heartbeat_at,
        next_event=lambda event_type, actor, payload: recorders[-1].prepare(
            event_type, actor, payload
        ),
        accept_event=lambda event: recorders[-1].accept_persisted_event(event),
        ownership_check=ownership_check,
        effect_payloads=effect_payloads,
        mutation_authority=cloud_effect_payloads.effect_authority_provider(
            recorders, enabled=effect_payloads is not None
        ),
        mutation_guard=lambda: recorders[-1].mutation(),
        execution_started=lambda call_id: recorders[-1].effect_started(call_id),
        payloadless_readonly=payloadless_readonly,
    )
