from dataclasses import dataclass
from pathlib import Path

from agent_core.ports import (
    AgentTaskPort,
    ArtifactPayloadReadPort,
    ArtifactPayloadStorePort,
    ContextLifecycleStorePort,
    DeliveryAuditStorePort,
    EffectLedgerPort,
    EventStorePort,
    HandoffDispatchStorePort,
    IdempotencyStorePort,
    LeaseStorePort,
    MemoryStorePort,
    ModelCallStorePort,
    ProjectionStorePort,
    ProviderContinuationStorePort,
    SessionArtifactReadPort,
    SessionHandoffPort,
    SessionHistoryPort,
    ToolRunStorePort,
    WorkspaceProjectionStorePort,
)

from agent_storage.agent_tasks import SQLiteAgentTaskStore
from agent_storage.artifact_payload_reads import LocalArtifactPayloadReader
from agent_storage.artifact_payloads import SQLiteArtifactPayloadStore
from agent_storage.artifacts import SQLiteArtifactStore
from agent_storage.context_lifecycle import SQLiteContextLifecycleStore
from agent_storage.delivery_audit import SQLiteDeliveryAuditStore
from agent_storage.effect_ledger import SQLiteEffectLedger
from agent_storage.idempotency import SQLiteIdempotencyStore
from agent_storage.leases import SQLiteLeaseStore
from agent_storage.memories import SQLiteMemoryStore
from agent_storage.model_calls import SQLiteModelCallStore
from agent_storage.projections import SQLiteProjectionStore
from agent_storage.provider_continuations import SQLiteProviderContinuationStore
from agent_storage.session_handoff_dispatch import SQLiteHandoffDispatchStore
from agent_storage.session_handoffs import SQLiteSessionHandoffStore
from agent_storage.session_history import SQLiteSessionHistory
from agent_storage.sqlite import SQLiteEventStore
from agent_storage.tool_runs import SQLiteToolRunStore
from agent_storage.workspaces import SQLiteWorkspaceProjectionStore


@dataclass(frozen=True, slots=True)
class ControlPlaneStores:
    events: EventStorePort
    sessions: ProjectionStorePort
    workspaces: WorkspaceProjectionStorePort
    tasks: AgentTaskPort
    leases: LeaseStorePort
    context_lifecycle: ContextLifecycleStorePort
    handoffs: SessionHandoffPort
    handoff_dispatch: HandoffDispatchStorePort
    idempotency: IdempotencyStorePort
    effects: EffectLedgerPort
    memories: MemoryStorePort
    artifact_payloads: ArtifactPayloadStorePort
    artifact_payload_reader: ArtifactPayloadReadPort
    model_calls: ModelCallStorePort
    tool_runs: ToolRunStorePort
    artifacts: SessionArtifactReadPort
    provider_continuations: ProviderContinuationStorePort
    session_history: SessionHistoryPort
    delivery_audit: DeliveryAuditStorePort

    @property
    def legacy_artifact_control_enabled(self) -> bool:
        reader = self.artifact_payload_reader
        return isinstance(reader, LocalArtifactPayloadReader) and reader.controls(
            self.artifact_payloads
        )


def sqlite_control_plane_stores(database_path: str | Path) -> ControlPlaneStores:
    local_path = Path(database_path)
    if str(local_path) == ":memory:":
        raise ValueError("sqlite control-plane composition requires a filesystem-backed database")
    model_calls = SQLiteModelCallStore(local_path)
    tool_runs = SQLiteToolRunStore(local_path)
    artifact_payloads = SQLiteArtifactPayloadStore(local_path)
    return ControlPlaneStores(
        events=SQLiteEventStore(local_path),
        sessions=SQLiteProjectionStore(local_path),
        workspaces=SQLiteWorkspaceProjectionStore(local_path),
        tasks=SQLiteAgentTaskStore(local_path),
        leases=SQLiteLeaseStore(local_path),
        context_lifecycle=SQLiteContextLifecycleStore(local_path),
        handoffs=SQLiteSessionHandoffStore(local_path),
        handoff_dispatch=SQLiteHandoffDispatchStore(local_path),
        idempotency=SQLiteIdempotencyStore(local_path),
        effects=SQLiteEffectLedger(local_path),
        memories=SQLiteMemoryStore(local_path),
        artifact_payloads=artifact_payloads,
        model_calls=model_calls,
        tool_runs=tool_runs,
        artifacts=SQLiteArtifactStore(model_calls, tool_runs),
        provider_continuations=SQLiteProviderContinuationStore(local_path),
        session_history=SQLiteSessionHistory(local_path),
        delivery_audit=SQLiteDeliveryAuditStore(local_path),
        artifact_payload_reader=LocalArtifactPayloadReader(artifact_payloads),
    )
