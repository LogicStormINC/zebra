from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agent_runtime.finos_journal_provider import FINOS_TOOL_SPECS_BY_CONTRACT
from agent_storage import FinosJournalGrant, SQLiteAgentTaskStore, SQLiteFinosJournalGrantStore
from agent_storage.model_tool_argument_values import (
    ModelToolArgumentValues,
    validate_model_tool_argument_values,
)

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
    store = SQLiteFinosJournalGrantStore(database_path)
    try:
        store.bind(
            FinosJournalGrant(
                task_id=parsed_task_id,
                contract_version=provider.contract_version,
                grant=provider.grant,
                expires_at=provider.expires_at,
                model_tool_names=provider.model_tool_names,
                model_tool_argument_values=provider.model_tool_argument_values,
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
    binding = store.get(parsed_task_id)
    if binding is None:
        return ApiResponse(409, {"task_id": task_id, "status": "conflict"})
    return ApiResponse(
        200,
        {
            "task_id": task_id,
            "business_tools": {
                "contract_version": provider.contract_version,
                "names": list(
                    binding.model_tool_names
                    or FINOS_JOURNAL_TOOLS_BY_CONTRACT[provider.contract_version]
                ),
            },
        },
    )


@dataclass(frozen=True)
class _ParsedFinosJournalProvider:
    contract_version: str
    grant: str
    expires_at: datetime
    model_tool_names: tuple[str, ...] | None
    model_tool_argument_values: ModelToolArgumentValues | None


def _parse_finos_journal_provider(raw: object) -> _ParsedFinosJournalProvider | ApiResponse:
    if not isinstance(raw, dict):
        return ApiResponse(
            400,
            {"status": "invalid_request", "reason": "finos_journal_provider must be an object"},
        )
    required_fields = {"contract_version", "grant", "expires_at"}
    optional_fields = {"model_tool_names", "model_tool_argument_values"}
    if not required_fields <= set(raw) <= required_fields | optional_fields:
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
    model_tool_names = _model_tool_names(raw, FINOS_JOURNAL_TOOLS_BY_CONTRACT[contract_version])
    if isinstance(model_tool_names, ApiResponse):
        return model_tool_names
    model_tool_argument_values = _model_tool_argument_values(
        raw,
        model_tool_names,
        {
            spec.contract.name: spec.contract.argument_properties
            for spec in FINOS_TOOL_SPECS_BY_CONTRACT[contract_version]
        },
    )
    if isinstance(model_tool_argument_values, ApiResponse):
        return model_tool_argument_values
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
        model_tool_names=model_tool_names,
        model_tool_argument_values=model_tool_argument_values,
    )


def _model_tool_names(
    raw: dict[str, object], catalog: tuple[str, ...]
) -> tuple[str, ...] | ApiResponse | None:
    if "model_tool_names" not in raw:
        return None
    value = raw["model_tool_names"]
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(name, str) and name.strip() for name in value)
        or len(set(value)) != len(value)
        or not set(value) <= set(catalog)
    ):
        return ApiResponse(
            400,
            {
                "status": "invalid_request",
                "reason": "model_tool_names must be a nonempty unique contract catalog subset",
            },
        )
    return tuple(name for name in catalog if name in value)


def _model_tool_argument_values(
    raw: dict[str, object],
    model_tool_names: tuple[str, ...] | None,
    catalog: dict[str, Mapping[str, Mapping[str, object]]],
) -> ModelToolArgumentValues | ApiResponse | None:
    if "model_tool_argument_values" not in raw:
        return None
    try:
        return validate_model_tool_argument_values(
            raw["model_tool_argument_values"],
            selected_tool_names=model_tool_names,
            catalog=catalog,
            require_lists=True,
        )
    except ValueError:
        return ApiResponse(
            400,
            {
                "status": "invalid_request",
                "reason": "model_tool_argument_values must constrain selected string values",
            },
        )
