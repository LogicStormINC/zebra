"""Storage adapters for Zebra Agent."""

from agent_storage.agent_tasks import SQLiteAgentTaskStore
from agent_storage.artifact_payloads import (
    ArtifactPayloadMissingError,
    SQLiteArtifactPayloadStore,
)
from agent_storage.artifact_projection import (
    payload_for_artifact_uri,
    serialize_artifact_lifecycle,
    serialize_artifact_retrieval,
    serialize_session_artifact_projection,
)
from agent_storage.artifacts import SessionArtifact, SQLiteArtifactStore
from agent_storage.context_lifecycle import (
    ActiveContextProjectionConflictError,
    ImmutableContextCapsuleConflictError,
    SQLiteContextLifecycleStore,
    StoredContextCapsule,
)
from agent_storage.delivery_audit import SQLiteDeliveryAuditStore
from agent_storage.effect_ledger import (
    EffectLedgerStatus,
    EffectReplayRejectedError,
    EffectReservation,
    SQLiteEffectLedger,
)
from agent_storage.idempotency import (
    IdempotencyConflictError,
    IdempotencyRecord,
    SQLiteIdempotencyStore,
    new_idempotency_record,
)
from agent_storage.leases import LeaseConflictError, SQLiteLeaseStore
from agent_storage.memories import SQLiteMemoryStore
from agent_storage.memory_lookup import (
    list_confirmed_repo_memories,
    list_confirmed_repo_memory_texts,
)
from agent_storage.model_calls import SQLiteModelCallStore
from agent_storage.projections import SQLiteProjectionStore
from agent_storage.provider_continuations import (
    LoadedProviderContinuation,
    SQLiteProviderContinuationStore,
)
from agent_storage.session_attachments import (
    load_attachment_contexts,
    store_initial_text_attachments,
    store_text_attachments,
)
from agent_storage.session_handoff_dispatch import SQLiteHandoffDispatchStore
from agent_storage.session_handoff_facts import HandoffSourceFacts
from agent_storage.session_handoff_rows import (
    HandoffDispatch,
    HandoffIdempotencyConflictError,
    HandoffStorageConflictError,
)
from agent_storage.session_handoffs import SQLiteSessionHandoffStore
from agent_storage.session_history import SQLiteSessionHistory
from agent_storage.skills_state import SkillStateRecord, SQLiteSkillsStateStore
from agent_storage.sqlite import SQLiteEventStore
from agent_storage.tool_runs import SQLiteToolRunStore
from agent_storage.workspaces import SQLiteWorkspaceProjectionStore

__all__ = [
    "ArtifactPayloadMissingError",
    "EffectLedgerStatus",
    "EffectReplayRejectedError",
    "EffectReservation",
    "ActiveContextProjectionConflictError",
    "IdempotencyConflictError",
    "IdempotencyRecord",
    "HandoffDispatch",
    "HandoffIdempotencyConflictError",
    "HandoffStorageConflictError",
    "HandoffSourceFacts",
    "ImmutableContextCapsuleConflictError",
    "LeaseConflictError",
    "SessionArtifact",
    "LoadedProviderContinuation",
    "list_confirmed_repo_memories",
    "SQLiteMemoryStore",
    "list_confirmed_repo_memory_texts",
    "load_attachment_contexts",
    "payload_for_artifact_uri",
    "serialize_artifact_lifecycle",
    "serialize_artifact_retrieval",
    "serialize_session_artifact_projection",
    "SQLiteArtifactPayloadStore",
    "SQLiteAgentTaskStore",
    "SQLiteArtifactStore",
    "SQLiteContextLifecycleStore",
    "SQLiteDeliveryAuditStore",
    "SQLiteEffectLedger",
    "SQLiteEventStore",
    "SQLiteIdempotencyStore",
    "SQLiteLeaseStore",
    "SQLiteModelCallStore",
    "SQLiteProjectionStore",
    "SQLiteProviderContinuationStore",
    "SQLiteSessionHistory",
    "SQLiteSkillsStateStore",
    "SQLiteHandoffDispatchStore",
    "SQLiteSessionHandoffStore",
    "SQLiteToolRunStore",
    "SQLiteWorkspaceProjectionStore",
    "SkillStateRecord",
    "StoredContextCapsule",
    "store_text_attachments",
    "store_initial_text_attachments",
    "new_idempotency_record",
]
