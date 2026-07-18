from pathlib import Path

import pytest
from agent_core.domain.identifiers import new_session_id, new_tool_call_id
from agent_core.domain.session_handoff import EffectIdentity
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_storage import EffectReplayRejectedError, SQLiteEffectLedger


def _identity() -> EffectIdentity:
    return EffectIdentity(
        authority_scope_hash="authority",
        tool_name="command.run",
        operation_kind="command.run",
        target_hash="target",
        canonical_effect_hash="effect",
    )


def test_succeeded_effect_replays_durable_result_without_new_execution(
    tmp_path: Path,
) -> None:
    ledger = SQLiteEffectLedger(tmp_path / "ledger.db")
    root = new_session_id()
    reservation = ledger.reserve(root, _identity())
    ledger.mark_executing(reservation)
    result = ToolResult(
        tool_call_id=new_tool_call_id(),
        status=ToolCallStatus.EXECUTED,
        output="done",
    )
    ledger.mark_succeeded(reservation, result)

    replay = ledger.reserve(root, _identity())

    assert replay.replay is True
    assert replay.result == result
    assert ledger.terminal_keys(root) == frozenset({_identity().ledger_key()})


def test_uncertain_effect_fails_closed(tmp_path: Path) -> None:
    ledger = SQLiteEffectLedger(tmp_path / "ledger.db")
    root = new_session_id()
    reservation = ledger.reserve(root, _identity())
    ledger.mark_executing(reservation)
    ledger.mark_uncertain(reservation)

    with pytest.raises(EffectReplayRejectedError, match="uncertain"):
        ledger.reserve(root, _identity())
    assert ledger.has_uncertain(root) is True
