from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlparse

from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_tools import ToolContract, ToolRegistry
from agent_tools.contracts import READ_ONLY_EFFECT_TAG

import agent_runtime.tool_contract_constraints as tool_contract_constraints

MAX_RESPONSE_BYTES = 524_288
AUTHORITATIVE_TYPED_READ = "authoritative_typed_read"
CONFIRMED_INVESTOR_KNOWLEDGE = "confirmed_investor_knowledge"
TRUSTED_TYPED_EVIDENCE_TAG_PREFIX = "internal:trusted_typed_evidence:"
FINOS_JOURNAL_V1_CONTRACT = "finos.journals.v1"
FINOS_JOURNAL_V2_CONTRACT = "finos.journals.v2"
FINOS_JOURNAL_V3_CONTRACT = "finos.journals.v3"
FINOS_JOURNAL_V4_CONTRACT = "finos.journals.v4"
SUPPORTED_FINOS_JOURNAL_CONTRACTS = frozenset(
    (FINOS_JOURNAL_V1_CONTRACT, FINOS_JOURNAL_V2_CONTRACT,
     FINOS_JOURNAL_V3_CONTRACT, FINOS_JOURNAL_V4_CONTRACT)
)
@dataclass(frozen=True)
class _FinosTool:
    contract: ToolContract
    suffix: str
    side_effect: str = "read_only"
    tags: tuple[str, ...] = ()
JOURNALS_LIST_CONTRACT = ToolContract(
    name="finos.journals.list",
    description="List authorized FinOS daily journals for this Task.",
    capability_version="finos.journals.list.v1",
    argument_properties={
        "account_id": {"type": "string", "minLength": 1, "maxLength": 128},
        "date_from": {"type": "string", "format": "date"},
        "date_to": {"type": "string", "format": "date"},
        "status": {
            "type": "string",
            "enum": ["saved", "pending_confirmation", "confirmed", "rejected"],
        },
        "cursor": {"type": "string", "minLength": 1, "maxLength": 512},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
    },
)
JOURNALS_GET_CONTRACT = ToolContract(
    name="finos.journals.get",
    description="Read one authorized FinOS daily journal for this Task.",
    capability_version="finos.journals.get.v1",
    required_arguments=("journal_id",),
    argument_properties={
        "journal_id": {"type": "string", "minLength": 1, "maxLength": 256},
    },
)
SNAPSHOTS_LIST_CONTRACT = ToolContract(
    name="finos.snapshots.list",
    description="List authorized FinOS confirmed account snapshots for this Task.",
    capability_version="finos.snapshots.list.v1",
    argument_properties={
        "account_id": {"type": "string", "minLength": 1, "maxLength": 128},
        "date_from": {"type": "string", "format": "date"},
        "date_to": {"type": "string", "format": "date"},
        "cursor": {"type": "string", "minLength": 1, "maxLength": 512},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
    },
)
SNAPSHOTS_GET_CONTRACT = ToolContract(
    name="finos.snapshots.get",
    description="Read one authorized FinOS confirmed account snapshot for this Task.",
    capability_version="finos.snapshots.get.v1",
    required_arguments=("snapshot_id",),
    argument_properties={
        "snapshot_id": {"type": "string", "minLength": 1, "maxLength": 256},
    },
)
TRANSACTIONS_LIST_CONTRACT = ToolContract(
    name="finos.transactions.list",
    description="List authorized FinOS confirmed transactions for this Task.",
    capability_version="finos.transactions.list.v1",
    argument_properties={
        "account_id": {"type": "string", "minLength": 1, "maxLength": 128},
        "symbol": {"type": "string", "minLength": 1, "maxLength": 32},
        "date_from": {"type": "string", "format": "date"},
        "date_to": {"type": "string", "format": "date"},
        "cursor": {"type": "string", "minLength": 1, "maxLength": 512},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
    },
)
POSITIONS_LIST_CONTRACT = ToolContract(
    name="finos.positions.list",
    description="List authorized current FinOS positions derived from confirmed Core data.",
    capability_version="finos.positions.list.v1",
    argument_properties={
        "account_id": {"type": "string", "minLength": 1, "maxLength": 128},
        "symbol": {"type": "string", "minLength": 1, "maxLength": 32},
    },
)
NOTES_LIST_CONTRACT = ToolContract(
    name="finos.notes.list",
    description="List authorized FinOS note metadata for this Task.",
    capability_version="finos.notes.list.v1",
    argument_properties={
        "tag": {"type": "string", "minLength": 1},
        "cursor": {"type": "string", "minLength": 1, "maxLength": 512},
        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
    },
)
NOTES_GET_CONTRACT = ToolContract(
    name="finos.notes.get",
    description="Read one authorized FinOS note for this Task.",
    capability_version="finos.notes.get.v1",
    required_arguments=("note_id",),
    argument_properties={
        "note_id": {"type": "string", "minLength": 1, "maxLength": 256},
    },
)
SECURITIES_RESOLVE_CONTRACT = ToolContract(
    name="finos.securities.resolve",
    description="Resolve one authorized FinOS security code, name, or alias.",
    capability_version="finos.securities.resolve.v1",
    required_arguments=("query",),
    argument_properties={
        "account_id": {"type": "string", "minLength": 1, "maxLength": 128},
        "query": {"type": "string", "minLength": 1, "maxLength": 128},
    },
)
ACCOUNT_CHANGES_PROPOSE_CONTRACT = ToolContract(
    name="finos.account_changes.propose",
    description="Record a typed account-change proposal for this authorized FinOS Task.",
    capability_version="finos.account_changes.propose.v1",
    required_arguments=("accounts", "evidence_coverage", "missing_evidence"),
    argument_properties={
        "accounts": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "account_ref": {"type": "string", "minLength": 1},
                    "transactions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind": {"type": "string", "minLength": 1},
                                "occurred_at": {"type": "string", "minLength": 1},
                                "source_type": {"type": "string", "minLength": 1},
                                "source_ref": {"type": "string", "minLength": 1},
                                "symbol": {"type": "string", "minLength": 1},
                                "display_name": {"type": "string", "minLength": 1},
                                "quantity": {"type": "string", "minLength": 1},
                                "price": {"type": "string", "minLength": 1},
                                "fee": {"type": "string", "minLength": 1},
                                "tax": {"type": "string", "minLength": 1},
                                "cash_amount": {"type": "string", "minLength": 1},
                            },
                            "required": [
                                "kind",
                                "occurred_at",
                                "source_type",
                                "source_ref",
                            ],
                            "additionalProperties": False,
                        },
                    },
                    "snapshot": {
                        "type": "object",
                        "properties": {
                            "captured_at": {"type": "string", "minLength": 1},
                            "total_assets": {"type": "string", "minLength": 1},
                            "cash": {"type": "string", "minLength": 1},
                            "market_value": {"type": "string", "minLength": 1},
                            "source_type": {"type": "string", "minLength": 1},
                            "source_ref": {"type": "string", "minLength": 1},
                            "holdings": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "symbol": {"type": "string", "minLength": 1},
                                        "display_name": {
                                            "type": "string",
                                            "minLength": 1,
                                        },
                                        "quantity": {"type": "string", "minLength": 1},
                                        "average_cost": {"type": "string", "minLength": 1},
                                        "snapshot_price": {
                                            "type": "string",
                                            "minLength": 1,
                                        },
                                        "market_value": {"type": "string", "minLength": 1},
                                        "unrealized_pnl": {
                                            "type": "string",
                                            "minLength": 1,
                                        },
                                        "unrealized_pnl_pct": {
                                            "type": "string",
                                            "minLength": 1,
                                        },
                                    },
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": [
                            "captured_at",
                            "total_assets",
                            "cash",
                            "market_value",
                            "source_type",
                            "source_ref",
                        ],
                        "additionalProperties": False,
                    },
                },
                "required": ["account_ref", "transactions"],
                "additionalProperties": False,
            },
        },
        "evidence_coverage": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "evidence_ref": {"type": "string", "minLength": 1},
                    "account": {"type": "string", "minLength": 1},
                    "captured_at": {"type": "string", "minLength": 1},
                    "covered_fields": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                    },
                    "read_status": {"type": "string", "minLength": 1},
                },
                "required": ["evidence_ref"],
                "additionalProperties": False,
            },
        },
        "missing_evidence": {"type": "array", "items": {"type": "string"}},
    },
)
JOURNALS_SAVE_CONTRACT = ToolContract(
    name="finos.journals.save",
    description=(
        "Save one completed final message of this authorized FinOS Task as a "
        "daily journal. The message must already be immutable in FinOS."
    ),
    capability_version="finos.journals.save.v1",
    required_arguments=("message_id", "source_artifact_id", "business_date", "idempotency_key"),
    argument_properties={
        "message_id": {"type": "string", "minLength": 1, "maxLength": 512},
        "source_artifact_id": {"type": "string", "minLength": 1, "maxLength": 256},
        "business_date": {"type": "string", "format": "date"},
        "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 256},
    },
)
TRADE_LOG_QUALITY_VALIDATE_CONTRACT = ToolContract(
    name="finos.trade_log_quality.validate",
    description=(
        "Validate one opaque structured candidate with the FinOS domain validator. "
        "The validator is read-only and returns a standard passed/issues result."
    ),
    capability_version="finos.trade_log_quality.validate.v1",
    required_arguments=("report",),
    argument_properties={"report": {"type": "object"}},
)
INVESTOR_KNOWLEDGE_LIST_CONTRACT = ToolContract(
    name="finos.investor_knowledge.list", description="List active confirmed Knowledge.",
    capability_version="finos.investor_knowledge.list.v1",
)
INVESTOR_KNOWLEDGE_GET_CONTRACT = ToolContract(
    name="finos.investor_knowledge.get", description="Read one confirmed Knowledge revision.",
    capability_version="finos.investor_knowledge.get.v1",
    required_arguments=("revision_id",),
    argument_properties={"revision_id": {"type": "string", "minLength": 1, "maxLength": 256}},
)
_AUTHORITATIVE_TYPED_READ_TAG = f"{TRUSTED_TYPED_EVIDENCE_TAG_PREFIX}{AUTHORITATIVE_TYPED_READ}"
_FINOS_FACTUAL_READ_TAGS = (_AUTHORITATIVE_TYPED_READ_TAG,)
FINOS_TOOL_SPECS = tuple(
    _FinosTool(contract, suffix, tags=_FINOS_FACTUAL_READ_TAGS)
    for contract, suffix in (
        (JOURNALS_LIST_CONTRACT, "journals:list"),
        (JOURNALS_GET_CONTRACT, "journals:get"),
        (SNAPSHOTS_LIST_CONTRACT, "snapshots:list"),
        (SNAPSHOTS_GET_CONTRACT, "snapshots:get"),
        (TRANSACTIONS_LIST_CONTRACT, "transactions:list"),
        (POSITIONS_LIST_CONTRACT, "positions:list"),
        (NOTES_LIST_CONTRACT, "notes:list"),
        (NOTES_GET_CONTRACT, "notes:get"),
        (SECURITIES_RESOLVE_CONTRACT, "securities:resolve"),
    )
)
FINOS_V2_TOOL_SPECS = (
    *FINOS_TOOL_SPECS,
    _FinosTool(ACCOUNT_CHANGES_PROPOSE_CONTRACT, "account-changes:propose", side_effect="proposal"),
    _FinosTool(JOURNALS_SAVE_CONTRACT, "journals:save", side_effect="journal_save"),
)
FINOS_V3_TOOL_SPECS = (
    *FINOS_V2_TOOL_SPECS,
    _FinosTool(
        TRADE_LOG_QUALITY_VALIDATE_CONTRACT, "trade-log-quality:validate", tags=("validator",)
    ),
)
_CONFIRMED_INVESTOR_KNOWLEDGE_TAGS = (
    f"{TRUSTED_TYPED_EVIDENCE_TAG_PREFIX}{CONFIRMED_INVESTOR_KNOWLEDGE}",
)
FINOS_V4_TOOL_SPECS = (
    *FINOS_V3_TOOL_SPECS,
    _FinosTool(
        INVESTOR_KNOWLEDGE_LIST_CONTRACT,
        "investor-knowledge:list",
        tags=_CONFIRMED_INVESTOR_KNOWLEDGE_TAGS,
    ),
    _FinosTool(
        INVESTOR_KNOWLEDGE_GET_CONTRACT,
        "investor-knowledge:get",
        tags=_CONFIRMED_INVESTOR_KNOWLEDGE_TAGS,
    ),
)
FINOS_TOOL_SPECS_BY_CONTRACT = {
    FINOS_JOURNAL_V1_CONTRACT: FINOS_TOOL_SPECS,
    FINOS_JOURNAL_V2_CONTRACT: FINOS_V2_TOOL_SPECS,
    FINOS_JOURNAL_V3_CONTRACT: FINOS_V3_TOOL_SPECS,
    FINOS_JOURNAL_V4_CONTRACT: FINOS_V4_TOOL_SPECS,
}
class FinosJournalTransport(Protocol):
    def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]: ...
@dataclass(frozen=True)
class FinosJournalProvider:
    base_url: str
    task_id: str
    grant: str = field(repr=False)
    contract_version: str = FINOS_JOURNAL_V1_CONTRACT
    model_tool_names: tuple[str, ...] | None = None
    model_tool_argument_values: tool_contract_constraints.ModelToolArgumentValues | None = None
    timeout_seconds: float = 10.0
    transport: FinosJournalTransport = field(default_factory=lambda: UrllibFinosTransport())
    def __post_init__(self) -> None:
        base_url = self.base_url.strip().rstrip("/")
        parsed = urlparse(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("FinOS provider base_url must use http or https")
        if not self.task_id.strip():
            raise ValueError("FinOS provider task_id must not be blank")
        if not self.grant.strip():
            raise ValueError("FinOS provider grant must not be blank")
        contract_version = (
            self.contract_version.strip() if isinstance(self.contract_version, str) else ""
        )
        if contract_version not in SUPPORTED_FINOS_JOURNAL_CONTRACTS:
            raise ValueError("FinOS provider contract_version is unsupported")
        if self.timeout_seconds <= 0:
            raise ValueError("FinOS provider timeout must be positive")
        object.__setattr__(self, "base_url", base_url)
        object.__setattr__(self, "task_id", self.task_id.strip())
        object.__setattr__(self, "grant", self.grant.strip())
        object.__setattr__(self, "contract_version", contract_version)

    def register(
        self,
        registry: ToolRegistry,
        *,
        allow_journal_save: bool = True,
    ) -> None:
        specs = FINOS_TOOL_SPECS_BY_CONTRACT[self.contract_version]
        selected = self.model_tool_names
        if not set(selected or ()) <= {spec.contract.name for spec in specs}:
            raise ValueError("business provider model_tool_names are invalid")
        contracts = tool_contract_constraints.constrained_tool_contracts(
            {spec.contract.name: spec.contract for spec in specs},
            self.model_tool_argument_values,
            selected,
        )
        for spec in specs:
            if selected is not None and spec.contract.name not in selected:
                continue
            if not allow_journal_save and spec.side_effect == "journal_save":
                # Saving stays a user-initiated message action, never a model tool call.
                continue
            tags = spec.tags
            if spec.side_effect == "read_only":
                tags += (READ_ONLY_EFFECT_TAG,)
            registry.register(contracts[spec.contract.name], self._handler(spec), tags=tags)
    def _handler(self, spec: _FinosTool) -> Callable[[ToolCall], ToolResult]:
        def handler(call: ToolCall) -> ToolResult:
            return self._execute(call, spec)

        return handler
    def _execute(self, call: ToolCall, spec: _FinosTool) -> ToolResult:
        if set(call.arguments) - set(spec.contract.argument_properties):
            return _failed(call, "FinOS provider tool arguments are invalid")
        try:
            response = self.transport.post_json(
                f"{self.base_url}/internal/agent-provider/v1/tasks/{self.task_id}/{spec.suffix}",
                headers={
                    "Authorization": f"Bearer {self.grant}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                payload={
                    "schema_version": f"{spec.contract.name}.request.v1",
                    **call.arguments,
                },
                timeout_seconds=self.timeout_seconds,
            )
        except Exception:
            return _failed(call, "FinOS provider request failed")
        response_schema = f"{spec.contract.name}.v1"
        if not isinstance(response, dict) or response.get("schema_version") != response_schema:
            return _failed(call, "FinOS provider returned an incompatible schema")
        try:
            output = json.dumps(response, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        except (TypeError, ValueError):
            return _failed(call, "FinOS provider returned an invalid response")
        if len(output.encode()) > MAX_RESPONSE_BYTES:
            return _failed(call, "FinOS provider response exceeds the size limit")
        metadata: dict[str, object] = {
            "schema_version": response_schema, "side_effect": spec.side_effect,
        }
        if "validator" in spec.tags:
            validator_result = _validator_result(response)
            if validator_result is None:
                return _failed(call, "FinOS provider returned an invalid validator result")
            metadata["validator_result"] = validator_result
        return ToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output=output,
            metadata=metadata,
        )
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None
@dataclass(frozen=True)
class UrllibFinosTransport:
    def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.build_opener(_NoRedirect()).open(
                request, timeout=timeout_seconds
            ) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raise ValueError(f"HTTP {exc.code}") from exc
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds size limit")
        try:
            parsed = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("response is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("response must be an object")
        return parsed
def _failed(call: ToolCall, detail: str) -> ToolResult:
    return ToolResult(
        tool_call_id=call.tool_call_id,
        status=ToolCallStatus.FAILED,
        metadata={"reason": "finos_journal_provider_error", "detail": detail[:1000]},
    )
def _validator_result(response: dict[str, object]) -> dict[str, object] | None:
    value = response.get("validator_result")
    if not isinstance(value, dict):
        return None
    if value.get("schema_version") != "zebra.validator-result.v1":
        return None
    passed = value.get("passed")
    issues = value.get("issues")
    if not isinstance(passed, bool) or not isinstance(issues, list):
        return None
    return {"passed": passed, "issue_count": len(issues)}
