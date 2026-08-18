from pathlib import Path

CONTRACT_PATH = (
    Path(__file__).parents[2] / "docs" / "ADR-018_Memory Provider Deletion Compliance Contract.md"
)


def _contract() -> str:
    return CONTRACT_PATH.read_text(encoding="utf-8")


def test_contract_requires_recovery_delete_and_complete_scoped_coverage() -> None:
    contract = _contract()

    for heading in (
        "### 1. Deterministic recovery",
        "### 2. Deterministic physical deletion",
        "### 3. Complete scoped coverage",
        "### 4. Unknown outcome handling",
        "### 5. Admission policy",
    ):
        assert heading in contract

    assert "Complete enumeration" in contract
    assert "Deterministic lookup" in contract
    assert "Atomic namespace drop" in contract
    assert "best-effort" in contract
    assert "is insufficient" in contract
    assert "top_k" in contract
    assert "global" in contract and "reset" in contract
    assert "No automatic retry" in contract or "never automatically retried" in contract


def test_mem0_is_fail_closed_without_unlocking_runtime() -> None:
    contract = _contract()

    expected_rows = (
        "| Ambiguous-create recovery | Yes |",
        "| Complete scoped physical deletion | Yes |",
        "| Runtime Memory admission | Yes |",
    )
    for row in expected_rows:
        assert row in contract

    assert "`FAIL/UNPROVEN`" in contract
    assert "`BLOCKED`" in contract
    assert "Mem0 is **not admitted to the Runtime mainline**" in contract
    assert "`MEM-GW-DEL-RUN-01`, its parent ledger task and Runtime composition stay" in contract
    assert "No Provider HTTP client, Mem0 adapter, Worker/Consumer, Desktop" in contract

    runtime_admission_row = next(
        line for line in contract.splitlines() if line.startswith("| Runtime Memory admission |")
    )
    assert "`BLOCKED`" in runtime_admission_row
    assert "`PASS`" not in runtime_admission_row
