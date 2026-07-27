from __future__ import annotations

import json
import urllib.error
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_core.domain.identifiers import new_tool_call_id
from agent_core.domain.tools import ToolCall, ToolCallStatus
from agent_runtime import FinosJournalProvider, LocalToolGateway
from agent_runtime.finos_journal_provider import MAX_RESPONSE_BYTES, UrllibFinosTransport


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


def _call(name: str, arguments: dict[str, object]) -> ToolCall:
    return ToolCall(
        tool_call_id=new_tool_call_id(),
        name=name,
        arguments=arguments,
        created_at=datetime.now(UTC),
    )
