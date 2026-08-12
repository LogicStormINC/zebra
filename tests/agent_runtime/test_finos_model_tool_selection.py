from pathlib import Path

import pytest
from agent_runtime import FinosJournalProvider, LocalToolGateway


def test_model_tool_selection_filters_only_business_provider_tools(tmp_path: Path) -> None:
    selected = ("finos.journals.list", "finos.trade_log_quality.validate")
    provider = FinosJournalProvider(
        base_url="https://finos.internal",
        task_id="11111111-1111-4111-8111-111111111111",
        grant="opaque-task-grant",
        contract_version="finos.journals.v3",
        model_tool_names=selected,
    )
    gateway = LocalToolGateway(tmp_path, finos_journal_provider=provider)
    names = {tool.name for tool in gateway.model_tools}

    assert {name for name in names if name.startswith("finos.")} == set(selected)
    assert {"agent.plan", "artifact.output_contract.emit"} <= names


def test_model_tool_selection_rejects_names_outside_the_contract(tmp_path: Path) -> None:
    provider = FinosJournalProvider(
        base_url="https://finos.internal",
        task_id="11111111-1111-4111-8111-111111111111",
        grant="opaque-task-grant",
        model_tool_names=("finos.unknown",),
    )

    with pytest.raises(ValueError, match="model_tool_names"):
        LocalToolGateway(tmp_path, finos_journal_provider=provider)
