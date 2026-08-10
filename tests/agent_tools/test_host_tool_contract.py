from __future__ import annotations

import pytest
from agent_tools.contracts import (
    MAX_TOOL_OUTPUT_BYTES,
    MAX_TOOL_TIMEOUT_SECONDS,
    ToolContract,
    ToolExecutionLocation,
    ToolIdempotency,
    ToolRisk,
)


def test_existing_contract_defaults_remain_local_and_bounded() -> None:
    contract = ToolContract(name="files.read")

    assert contract.execution_location is ToolExecutionLocation.ZEBRA
    assert contract.scopes == ()
    assert contract.risk is ToolRisk.READ
    assert contract.timeout_seconds == 30
    assert contract.max_output_bytes == 32_768
    assert contract.idempotency is ToolIdempotency.NONE


def test_host_contract_normalizes_scope_and_builds_non_secret_receipt() -> None:
    contract = ToolContract(
        name="host.trench.read",
        execution_location=ToolExecutionLocation.HOST,
        scopes=(" trench:event:read ",),
        risk=ToolRisk.READ,
        idempotency=ToolIdempotency.REQUIRED,
        timeout_seconds=20,
        max_output_bytes=10_000,
    )

    receipt = contract.receipt(status="executed", output_bytes=12, idempotency_key="r-1")

    assert contract.scopes == ("trench:event:read",)
    assert receipt.as_metadata() == {
        "schema_version": "1",
        "tool_name": "host.trench.read",
        "execution_location": "host",
        "scopes": ["trench:event:read"],
        "risk": "read",
        "status": "executed",
        "output_bytes": 12,
        "idempotency_key": "r-1",
    }


def test_host_requires_scope_and_required_idempotency_key() -> None:
    with pytest.raises(ValueError, match="require at least one scope"):
        ToolContract(name="host.read", execution_location=ToolExecutionLocation.HOST)

    contract = ToolContract(
        name="host.write",
        execution_location=ToolExecutionLocation.HOST,
        scopes=("trench:event:write",),
        idempotency=ToolIdempotency.REQUIRED,
    )
    with pytest.raises(ValueError, match="idempotency key"):
        contract.receipt(status="failed", output_bytes=0)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("scopes", ("read", "read")),
        ("timeout_seconds", 0),
        ("timeout_seconds", MAX_TOOL_TIMEOUT_SECONDS + 1),
        ("max_output_bytes", 0),
        ("max_output_bytes", MAX_TOOL_OUTPUT_BYTES + 1),
    ),
)
def test_host_contract_rejects_duplicate_or_unbounded_metadata(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        ToolContract(
            name="host.read",
            execution_location=ToolExecutionLocation.HOST,
            scopes=("read",) if field != "scopes" else value,
            **({field: value} if field != "scopes" else {}),
        )
