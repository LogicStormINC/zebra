from __future__ import annotations

import json
import urllib.error
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.domain.identifiers import new_session_id, new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_runtime import FinosJournalProvider, LocalToolGateway
from agent_runtime.finos_journal_provider import MAX_RESPONSE_BYTES, UrllibFinosTransport
from agent_storage import SQLiteEffectLedger
from agent_tools import EffectGuardedToolGateway


class RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str], dict[str, object], float]] = []

    def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        self.calls.append((url, headers, payload, timeout_seconds))
        return {
            "schema_version": str(payload["schema_version"]).replace(".request", ""),
            "records": [],
        }


class FailingTransport:
    def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        raise OSError("private transport failure")


class OversizedTransport:
    def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        return {
            "schema_version": "finos.journals.list.v1",
            "records": ["x" * MAX_RESPONSE_BYTES],
        }


class MismatchedSchemaTransport:
    def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        return {"schema_version": "finos.journals.get.v1", "records": []}


def test_fixed_business_catalog_hides_authority_and_uses_fixed_paths_and_schemas(
    tmp_path: Path,
) -> None:
    transport = RecordingTransport()
    task_id = "11111111-1111-4111-8111-111111111111"
    grant = "opaque-task-grant"
    provider = FinosJournalProvider(
        base_url="https://finos.internal",
        task_id=task_id,
        grant=grant,
        transport=transport,
    )
    gateway = LocalToolGateway(tmp_path, finos_journal_provider=provider)
    expected = (
        (
            "finos.journals.list",
            "journals:list",
            {"account_id": "all", "status": "saved", "limit": 20},
        ),
        ("finos.journals.get", "journals:get", {"journal_id": "journal-1"}),
        (
            "finos.snapshots.list",
            "snapshots:list",
            {"account_id": "all", "date_from": "2026-07-01", "date_to": "2026-07-31", "limit": 20},
        ),
        ("finos.snapshots.get", "snapshots:get", {"snapshot_id": "snapshot-1"}),
        (
            "finos.transactions.list",
            "transactions:list",
            {
                "account_id": "all",
                "symbol": "600000",
                "date_from": "2026-07-01",
                "date_to": "2026-07-31",
                "limit": 20,
            },
        ),
        ("finos.notes.list", "notes:list", {"tag": "rebalance", "limit": 20}),
        ("finos.notes.get", "notes:get", {"note_id": "note-1"}),
        (
            "finos.securities.resolve",
            "securities:resolve",
            {"account_id": "all", "query": "600000"},
        ),
    )

    definitions = {
        item.name: item.parameters for item in gateway.model_tools if item.name.startswith("finos.")
    }
    assert set(definitions) == {name for name, _, _ in expected}
    serialized = json.dumps(definitions, sort_keys=True)
    for hidden in ("url", "owner", "task_id", "grant", "refresh"):
        assert hidden not in serialized
    assert definitions["finos.journals.list"]["properties"]["status"]["enum"] == [
        "saved",
        "pending_confirmation",
        "confirmed",
        "rejected",
    ]
    assert set(definitions["finos.notes.list"]["properties"]) == {"tag", "cursor", "limit"}
    assert definitions["finos.notes.list"]["properties"]["limit"]["maximum"] == 20
    assert definitions["finos.securities.resolve"]["properties"]["account_id"]["maxLength"] == 128
    assert definitions["finos.securities.resolve"]["properties"]["query"]["maxLength"] == 128

    for name, suffix, arguments in expected:
        result = gateway.execute(_call(name, arguments))
        url, headers, payload, _ = transport.calls[-1]

        assert result.status is ToolCallStatus.EXECUTED
        assert result.metadata == {
            "schema_version": f"{name}.v1",
            "side_effect": "read_only",
        }
        assert url == f"https://finos.internal/internal/agent-provider/v1/tasks/{task_id}/{suffix}"
        assert headers["Authorization"] == f"Bearer {grant}"
        assert payload == {"schema_version": f"{name}.request.v1", **arguments}

    rejected = gateway.execute(_call("finos.journals.list", {"refresh": True}))
    notes_query = gateway.execute(_call("finos.notes.list", {"query": "rebalance"}))
    assert rejected.status is ToolCallStatus.FAILED
    assert notes_query.status is ToolCallStatus.FAILED
    assert len(transport.calls) == len(expected)
    assert grant not in repr(provider)
    assert grant not in str(rejected)


def test_v2_business_catalog_adds_only_typed_account_change_proposal(
    tmp_path: Path,
) -> None:
    transport = RecordingTransport()
    task_id = "11111111-1111-4111-8111-111111111111"
    provider = FinosJournalProvider(
        base_url="https://finos.internal",
        task_id=task_id,
        grant="opaque-task-grant",
        contract_version="finos.journals.v2",
        transport=transport,
    )
    gateway = LocalToolGateway(tmp_path, finos_journal_provider=provider)
    proposal_name = "finos.account_changes.propose"
    definitions = {
        item.name: item.parameters for item in gateway.model_tools if item.name.startswith("finos.")
    }

    assert provider.contract_version == "finos.journals.v2"
    assert set(definitions) == {
        "finos.journals.list",
        "finos.journals.get",
        "finos.snapshots.list",
        "finos.snapshots.get",
        "finos.transactions.list",
        "finos.notes.list",
        "finos.notes.get",
        "finos.securities.resolve",
        proposal_name,
    }
    assert definitions[proposal_name]["required"] == [
        "accounts",
        "evidence_coverage",
        "missing_evidence",
    ]
    assert set(definitions[proposal_name]["properties"]) == {
        "accounts",
        "evidence_coverage",
        "missing_evidence",
    }

    arguments = {
        "accounts": [{"account_ref": "portfolio-main", "transactions": []}],
        "evidence_coverage": [],
        "missing_evidence": [],
    }
    result = gateway.execute(_call(proposal_name, arguments))
    url, _, payload, _ = transport.calls[-1]

    assert result.status is ToolCallStatus.EXECUTED
    assert result.metadata == {
        "schema_version": "finos.account_changes.propose.v1",
        "side_effect": "proposal",
    }
    assert url == (
        "https://finos.internal/internal/agent-provider/v1/tasks/"
        f"{task_id}/account-changes:propose"
    )
    assert payload == {
        "schema_version": "finos.account_changes.propose.request.v1",
        **arguments,
    }


def test_v2_account_change_schema_exposes_finos_nested_typed_contract(
    tmp_path: Path,
) -> None:
    provider = FinosJournalProvider(
        base_url="https://finos.internal",
        task_id="11111111-1111-4111-8111-111111111111",
        grant="opaque-task-grant",
        contract_version="finos.journals.v2",
        transport=RecordingTransport(),
    )
    gateway = LocalToolGateway(tmp_path, finos_journal_provider=provider)
    definition = next(
        item.parameters
        for item in gateway.model_tools
        if item.name == "finos.account_changes.propose"
    )

    account = definition["properties"]["accounts"]["items"]
    assert account["required"] == ["account_ref", "transactions"]
    assert set(account["properties"]) == {"account_ref", "transactions", "snapshot"}

    transaction = account["properties"]["transactions"]["items"]
    assert transaction["required"] == ["kind", "occurred_at", "source_type", "source_ref"]
    assert set(transaction["properties"]) == {
        "kind",
        "occurred_at",
        "source_type",
        "source_ref",
        "symbol",
        "display_name",
        "quantity",
        "price",
        "fee",
        "tax",
        "cash_amount",
    }

    snapshot = account["properties"]["snapshot"]
    assert snapshot["required"] == [
        "captured_at",
        "total_assets",
        "cash",
        "market_value",
        "source_type",
        "source_ref",
    ]
    assert set(snapshot["properties"]) == {
        "captured_at",
        "total_assets",
        "cash",
        "market_value",
        "source_type",
        "source_ref",
        "holdings",
    }

    holding = snapshot["properties"]["holdings"]["items"]
    assert set(holding["properties"]) == {
        "symbol",
        "display_name",
        "quantity",
        "average_cost",
        "snapshot_price",
        "market_value",
        "unrealized_pnl",
        "unrealized_pnl_pct",
    }

    evidence = definition["properties"]["evidence_coverage"]["items"]
    assert evidence["required"] == ["evidence_ref"]
    assert evidence["properties"] == {
        "evidence_ref": {"type": "string", "minLength": 1},
        "account": {"type": "string", "minLength": 1},
        "captured_at": {"type": "string", "minLength": 1},
        "covered_fields": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "read_status": {"type": "string", "minLength": 1},
    }
    assert evidence["additionalProperties"] is False


def test_v2_account_change_proposal_rejects_wrong_evidence_items_before_transport(
    tmp_path: Path,
) -> None:
    transport = RecordingTransport()
    provider = FinosJournalProvider(
        base_url="https://finos.internal",
        task_id="11111111-1111-4111-8111-111111111111",
        grant="opaque-task-grant",
        contract_version="finos.journals.v2",
        transport=transport,
    )
    gateway = LocalToolGateway(tmp_path, finos_journal_provider=provider)

    result = gateway.execute(
        _call(
            "finos.account_changes.propose",
            {
                "accounts": [{"account_ref": "portfolio-main", "transactions": []}],
                "evidence_coverage": ["sensitive-evidence-text"],
                "missing_evidence": [],
            },
        )
    )

    assert result.status is ToolCallStatus.FAILED
    assert result.metadata["reason"] == "tool_validation_error"
    assert "evidence_coverage[0]" in str(result.metadata["detail"])
    assert "sensitive-evidence-text" not in str(result.metadata["detail"])
    assert transport.calls == []


def test_v3_catalog_exposes_a_generic_read_only_validator_result_contract(
    tmp_path: Path,
) -> None:
    class ValidatorTransport(RecordingTransport):
        def post_json(self, url, *, headers, payload, timeout_seconds):  # type: ignore[no-untyped-def]
            self.calls.append((url, headers, payload, timeout_seconds))
            return {
                "schema_version": "finos.trade_log_quality.validate.v1",
                "validator_result": {
                    "schema_version": "zebra.validator-result.v1",
                    "passed": False,
                    "issues": [{"code": "fixture_mismatch"}],
                },
            }

    transport = ValidatorTransport()
    provider = FinosJournalProvider(
        base_url="https://finos.internal",
        task_id="11111111-1111-4111-8111-111111111111",
        grant="opaque-task-grant",
        contract_version="finos.journals.v3",
        transport=transport,
    )
    gateway = LocalToolGateway(tmp_path, finos_journal_provider=provider)
    tool_name = "finos.trade_log_quality.validate"

    result = gateway.execute(_call(tool_name, {"report": {"trade_date": "2026-07-29"}}))

    assert tool_name in {item.name for item in gateway.model_tools}
    assert gateway.validator_tools == frozenset({tool_name})
    assert result.status is ToolCallStatus.EXECUTED
    assert result.metadata == {
        "schema_version": "finos.trade_log_quality.validate.v1",
        "side_effect": "read_only",
        "validator_result": {"passed": False, "issue_count": 1},
    }
    assert transport.calls[-1][0].endswith("/trade-log-quality:validate")
    assert transport.calls[-1][2] == {
        "schema_version": "finos.trade_log_quality.validate.request.v1",
        "report": {"trade_date": "2026-07-29"},
    }


def test_business_provider_rejects_unsupported_contract_version(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="contract_version"):
        FinosJournalProvider(
            base_url="https://finos.internal",
            task_id="11111111-1111-4111-8111-111111111111",
            grant="private-grant",
            contract_version="finos.journals.v4",
            transport=RecordingTransport(),
        )


def test_business_provider_fails_closed_for_transport_schema_and_size_errors(
    tmp_path: Path,
) -> None:
    call = _call("finos.journals.list", {"limit": 1})
    for transport in (FailingTransport(), MismatchedSchemaTransport(), OversizedTransport()):
        provider = FinosJournalProvider(
            base_url="https://finos.internal",
            task_id="11111111-1111-4111-8111-111111111111",
            grant="private-grant",
            transport=transport,
        )
        result = LocalToolGateway(tmp_path, finos_journal_provider=provider).execute(call)

        assert result.status is ToolCallStatus.FAILED
        assert result.metadata["reason"] == "finos_journal_provider_error"
        assert "private-grant" not in str(result)


def test_urllib_business_provider_transport_does_not_follow_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handlers = []

    class RedirectingOpener:
        def open(self, request, timeout: float):  # type: ignore[no-untyped-def]
            raise urllib.error.HTTPError(request.full_url, 302, "redirect", {}, None)

    def build_opener(*installed):  # type: ignore[no-untyped-def]
        handlers.extend(installed)
        return RedirectingOpener()

    monkeypatch.setattr(
        "agent_runtime.finos_journal_provider.urllib.request.build_opener",
        build_opener,
    )

    with pytest.raises(ValueError, match="HTTP 302"):
        UrllibFinosTransport().post_json(
            "https://finos.internal/internal/agent-provider/v1/tasks/task/journals:list",
            headers={},
            payload={"schema_version": "finos.journals.list.request.v1"},
            timeout_seconds=1,
        )

    assert len(handlers) == 1
    assert handlers[0].redirect_request(None, None, 302, "redirect", {}, "https://other") is None


def test_read_only_finos_tool_failure_bypasses_effect_ledger(tmp_path: Path) -> None:
    provider = FinosJournalProvider(
        base_url="https://finos.internal",
        task_id="11111111-1111-4111-8111-111111111111",
        grant="opaque-task-grant",
        contract_version="finos.journals.v2",
        transport=FailingTransport(),
    )
    gateway = LocalToolGateway(tmp_path, finos_journal_provider=provider)

    assert "finos.notes.list" in gateway.read_only_tools
    assert "finos.journals.list" in gateway.read_only_tools
    assert "finos.account_changes.propose" not in gateway.read_only_tools

    root_session_id = new_session_id()
    guarded = EffectGuardedToolGateway(
        gateway,
        ledger=SQLiteEffectLedger(tmp_path / "ledger.db"),
        root_session_id=root_session_id,
        authority_scope="workspace-write",
    )

    result = guarded.execute(_call("finos.notes.list", {"tag": "rebalance", "limit": 20}))

    assert result.status is ToolCallStatus.FAILED
    ledger = SQLiteEffectLedger(tmp_path / "ledger.db")
    assert ledger.has_uncertain(root_session_id) is False
    assert ledger.terminal_keys(root_session_id) == frozenset()


def _call(name: str, arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=datetime.now(UTC),
    )
