from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agent_storage import FinosJournalGrant, SQLiteAgentTaskStore, SQLiteFinosJournalGrantStore

from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.task_api import _not_found, parse_task_id

FINOS_JOURNAL_V1_CONTRACT = "finos.journals.v1"
FINOS_JOURNAL_V2_CONTRACT = "finos.journals.v2"
FINOS_JOURNAL_V3_CONTRACT = "finos.journals.v3"
FINOS_JOURNAL_V4_CONTRACT = "finos.journals.v4"
FINOS_JOURNAL_TOOLS = (
    "finos.journals.list",
    "finos.journals.get",
    "finos.snapshots.list",
    "finos.snapshots.get",
    "finos.transactions.list",
    "finos.positions.list",
    "finos.notes.list",
    "finos.notes.get",
    "finos.securities.resolve",
)
FINOS_JOURNAL_TOOLS_BY_CONTRACT = {
    FINOS_JOURNAL_V1_CONTRACT: FINOS_JOURNAL_TOOLS,
    FINOS_JOURNAL_V2_CONTRACT: (
        *FINOS_JOURNAL_TOOLS,
        "finos.account_changes.propose",
        "finos.journals.save",
    ),
    FINOS_JOURNAL_V3_CONTRACT: (
        *FINOS_JOURNAL_TOOLS,
        "finos.account_changes.propose",
        "finos.journals.save",
        "finos.trade_log_quality.validate",
    ),
    FINOS_JOURNAL_V4_CONTRACT: (
        *FINOS_JOURNAL_TOOLS,
        "finos.account_changes.propose",
        "finos.journals.save",
        "finos.trade_log_quality.validate",
        "finos.investor_knowledge.list",
        "finos.investor_knowledge.get",
    ),
}


def bind_finos_journal_provider(
    database_path: Path,
    task_id: str,
    payload: dict[str, object],
) -> ApiResponse:
    parsed_task_id = parse_task_id(task_id)
    if isinstance(parsed_task_id, ApiResponse):
        return parsed_task_id
    if SQLiteAgentTaskStore(database_path).get_task(parsed_task_id) is None:
        return _not_found(task_id)
    provider = _parse_finos_journal_provider(payload)
    if isinstance(provider, ApiResponse):
        return provider
    try:
        SQLiteFinosJournalGrantStore(database_path).bind(
            FinosJournalGrant(
                task_id=parsed_task_id,
                contract_version=provider.contract_version,
                grant=provider.grant,
                expires_at=provider.expires_at,
            )
        )
    except ValueError:
        return ApiResponse(
            409,
            {
                "task_id": task_id,
                "status": "conflict",
                "reason": "FinOS Journal provider rotation is stale or incompatible",
            },
        )
    return ApiResponse(
        200,
        {
            "task_id": task_id,
            "business_tools": {
                "contract_version": provider.contract_version,
                "names": list(FINOS_JOURNAL_TOOLS_BY_CONTRACT[provider.contract_version]),
            },
        },
    )


@dataclass(frozen=True)
class _ParsedFinosJournalProvider:
    contract_version: str
    grant: str
    expires_at: datetime


def _parse_finos_journal_provider(raw: object) -> _ParsedFinosJournalProvider | ApiResponse:
    if not isinstance(raw, dict):
        return ApiResponse(
            400,
            {"status": "invalid_request", "reason": "finos_journal_provider must be an object"},
        )
    if set(raw) != {"contract_version", "grant", "expires_at"}:
        return ApiResponse(
            400,
            {
                "status": "invalid_request",
                "reason": "finos_journal_provider has unsupported fields",
            },
        )
    contract_version = raw.get("contract_version")
    if contract_version not in FINOS_JOURNAL_TOOLS_BY_CONTRACT:
        return ApiResponse(
            400,
            {"status": "invalid_request", "reason": "FinOS Journal contract is unsupported"},
        )
    grant = raw.get("grant")
    if not isinstance(grant, str) or not grant.strip() or len(grant) > 4096:
        return ApiResponse(
            400,
            {"status": "invalid_request", "reason": "FinOS Journal grant is invalid"},
        )
    expires_at = raw.get("expires_at")
    try:
        parsed_expiry = datetime.fromisoformat(expires_at) if isinstance(expires_at, str) else None
    except ValueError:
        parsed_expiry = None
    if (
        parsed_expiry is None
        or parsed_expiry.tzinfo is None
        or parsed_expiry.utcoffset() is None
        or parsed_expiry <= datetime.now(UTC)
    ):
        return ApiResponse(
            400,
            {"status": "invalid_request", "reason": "FinOS Journal grant expiry is invalid"},
        )
    return _ParsedFinosJournalProvider(
        contract_version=contract_version,
        grant=grant.strip(),
        expires_at=parsed_expiry,
    )
