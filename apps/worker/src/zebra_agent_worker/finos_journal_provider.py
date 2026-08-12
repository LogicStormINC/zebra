from __future__ import annotations

from pathlib import Path

from agent_core.domain.identifiers import SessionId
from agent_runtime import FinosJournalProvider, FinosJournalTransport
from agent_storage import SQLiteAgentTaskStore, SQLiteFinosJournalGrantStore
from zebra_agent_config import ZebraAgentSettings

FINOS_JOURNAL_V1_CONTRACT = "finos.journals.v1"
FINOS_JOURNAL_V2_CONTRACT = "finos.journals.v2"
FINOS_JOURNAL_V3_CONTRACT = "finos.journals.v3"
FINOS_JOURNAL_V4_CONTRACT = "finos.journals.v4"
SUPPORTED_FINOS_JOURNAL_CONTRACTS = frozenset(
    {
        FINOS_JOURNAL_V1_CONTRACT,
        FINOS_JOURNAL_V2_CONTRACT,
        FINOS_JOURNAL_V3_CONTRACT,
        FINOS_JOURNAL_V4_CONTRACT,
    }
)


def allows_finos_account_changes_proposal(provider: FinosJournalProvider | None) -> bool:
    return provider is not None and provider.contract_version in {
        FINOS_JOURNAL_V2_CONTRACT,
        FINOS_JOURNAL_V3_CONTRACT,
        FINOS_JOURNAL_V4_CONTRACT,
    }


def build_finos_journal_provider(
    *,
    settings: ZebraAgentSettings,
    database_path: Path,
    session_id: SessionId,
    transport: FinosJournalTransport | None = None,
) -> FinosJournalProvider | None:
    base_url = settings.finos_journal_provider.base_url
    if base_url is None:
        return None
    task = SQLiteAgentTaskStore(database_path).ensure_for_session(session_id)
    binding = SQLiteFinosJournalGrantStore(database_path).get(task.task_id)
    if (
        binding is None
        or not binding.active
        or binding.contract_version not in SUPPORTED_FINOS_JOURNAL_CONTRACTS
    ):
        return None
    kwargs = {"transport": transport} if transport is not None else {}
    return FinosJournalProvider(
        base_url=base_url,
        task_id=str(task.task_id),
        grant=binding.grant,
        contract_version=binding.contract_version,
        model_tool_names=binding.model_tool_names,
        timeout_seconds=settings.finos_journal_provider.timeout_seconds,
        **kwargs,
    )
