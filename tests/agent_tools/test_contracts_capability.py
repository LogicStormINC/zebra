from __future__ import annotations

import pytest
from agent_tools.contracts import ToolContract


def test_contract_defaults_capability_version_to_one() -> None:
    contract = ToolContract(name="web.fetch")

    assert contract.capability_version == "1"


def test_contract_accepts_explicit_capability_version() -> None:
    contract = ToolContract(name="web.fetch", capability_version="2")

    assert contract.capability_version == "2"


@pytest.mark.parametrize("value", ("", "   "))
def test_contract_rejects_blank_capability_version(value: str) -> None:
    with pytest.raises(ValueError):
        ToolContract(name="web.fetch", capability_version=value)


def test_existing_contracts_keep_default_version_without_changes() -> None:
    from agent_tools.web_gateway import web_fetch_contract
    from agent_tools.web_search import web_search_contract

    assert web_fetch_contract.capability_version == "1"
    assert web_search_contract.capability_version == "1"
