"""Context package for Zebra Agent."""

from agent_context.adapter import LocalContextCompiler
from agent_context.compaction import (
    ConversationCompactionRequest,
    ToolOutputCompactionRequest,
    ToolOutputEvidence,
    compact_conversation,
    compact_tool_outputs,
)
from agent_context.compiler import compile_context
from agent_context.conversation import (
    PROVENANCE,
    SUMMARY_MARKER,
    compact_message_history,
    estimate_message_tokens,
)
from agent_context.materialization import (
    MaterializedContextInputs,
    context_inputs_from_delegated_snapshot,
    context_inputs_from_materialization,
    delegated_context_from_materialization,
)
from agent_context.models import (
    CompiledContext,
    ContextBudget,
    ContextCompileRequest,
    ContextItem,
    ContextItemKind,
    ContextProvenance,
    TrustLevel,
)
from agent_context.projection import (
    build_active_context_projection,
    build_protected_instruction_ledger,
    rehydrate_projection,
)
from agent_context.projection_models import (
    LEDGER_MARKER,
    PROJECTED_CALL_MARKER,
    TOMBSTONE_MARKER,
    ActiveContextProjection,
    FoldedToolExchange,
    ProtectedInstruction,
    ProtectedInstructionKind,
    ProtectedInstructionLedger,
    ToolResultTombstone,
)
from agent_context.prompt_layout import (
    PromptCacheKeyRequest,
    PromptLayout,
    PromptSection,
    PromptSectionKind,
    build_prompt_cache_key,
    build_prompt_layout,
)
from agent_context.ranking import rank_files, score_file
from agent_context.related import recall_related_files
from agent_context.scanner import ScannedFile, build_repo_map_item, scan_workspace_files
from agent_context.session_handoff import (
    HandoffEnvelopeBuildInput,
    build_handoff_envelope,
    handoff_runtime_evidence,
)
from agent_context.trust import prompt_injection_metadata, trust_level_for_item

__all__ = [
    "CompiledContext",
    "ActiveContextProjection",
    "build_prompt_cache_key",
    "build_prompt_layout",
    "LocalContextCompiler",
    "MaterializedContextInputs",
    "compact_conversation",
    "compact_tool_outputs",
    "compact_message_history",
    "ConversationCompactionRequest",
    "ContextBudget",
    "ContextCompileRequest",
    "ContextItem",
    "ContextItemKind",
    "ContextProvenance",
    "FoldedToolExchange",
    "HandoffEnvelopeBuildInput",
    "LEDGER_MARKER",
    "PromptCacheKeyRequest",
    "PromptLayout",
    "PromptSection",
    "PromptSectionKind",
    "PROJECTED_CALL_MARKER",
    "ProtectedInstruction",
    "ProtectedInstructionKind",
    "ProtectedInstructionLedger",
    "PROVENANCE",
    "ScannedFile",
    "build_repo_map_item",
    "build_handoff_envelope",
    "compile_context",
    "context_inputs_from_delegated_snapshot",
    "context_inputs_from_materialization",
    "delegated_context_from_materialization",
    "rank_files",
    "recall_related_files",
    "scan_workspace_files",
    "score_file",
    "SUMMARY_MARKER",
    "TOMBSTONE_MARKER",
    "ToolOutputCompactionRequest",
    "ToolOutputEvidence",
    "ToolResultTombstone",
    "TrustLevel",
    "prompt_injection_metadata",
    "build_active_context_projection",
    "build_protected_instruction_ledger",
    "estimate_message_tokens",
    "handoff_runtime_evidence",
    "rehydrate_projection",
    "trust_level_for_item",
]
