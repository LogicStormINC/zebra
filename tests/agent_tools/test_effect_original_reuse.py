"""Business-identical deferred replay must resolve, never wait on the old Run."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_core.domain.effect_dispatch import EffectDispatch, EffectDispatchStatus
from agent_core.domain.identifiers import new_event_id, new_session_id
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_storage import SQLiteArtifactPayloadStore, SQLiteEffectLedger
from agent_tools import EffectGuardedToolGateway, FencedEffectToolGateway
from agent_tools.effect_guard_support import effect_identity

from tests.agent_tools.test_effect_guard import _call, _fence, _Gateway


class HistoricalGateway(_Gateway):
    def __init__(self):
        super().__init__()
        self.reads = 0

    def execute(self, call):
        self.calls += 1
        return ToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            metadata={"client_effect_deferred": True, "client_effect_id": str(uuid4())},
        )

    def reconcile_deferred_result(self, call, original):
        self.reads += 1
        return ToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            metadata={"historical_client_effect": True},
        )


@pytest.mark.parametrize("fenced", [False, True])
def test_reused_deferred_is_resolved_without_reexecution(tmp_path, fenced):
    root, adapter, call = new_session_id(), HistoricalGateway(), _call("app.ui.item.open")
    if not fenced:
        guarded = EffectGuardedToolGateway(
            adapter,
            ledger=SQLiteEffectLedger(tmp_path / "ledger.db"),
            root_session_id=root,
            authority_scope="scope",
        )
        original = guarded.execute(call)
    else:
        original = adapter.execute(call)
        identity = effect_identity(call, "scope")
        record = EffectDispatch(
            dispatch_id=uuid4(),
            execution_session_id=root,
            root_session_id=root,
            identity=identity,
            attempt=1,
            request_hash=identity.canonical_effect_hash,
            payload_artifact_ref="persisted-original",
            status=EffectDispatchStatus.SUCCEEDED,
            intent_event_id=new_event_id(),
            terminal_event_id=new_event_id(),
            result=original,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        class ReadOnlyLedger:
            def find_by_ledger_key(self, root_session_id, *, identity):
                assert root_session_id == root
                return record

        guarded = FencedEffectToolGateway(
            adapter,
            dispatch=ReadOnlyLedger(),
            artifacts=SQLiteArtifactPayloadStore(tmp_path / "payloads.db"),
            execution_session_id=new_session_id(),
            root_session_id=root,
            fence=_fence(),
            claim_ttl=timedelta(seconds=10),
            authority_scope="scope",
            next_event=lambda *args: pytest.fail("replay emitted event"),
            accept_event=lambda event: pytest.fail("replay mutated ledger"),
            ownership_check=lambda: None,
        )
    next_call = call.model_copy(update={"tool_call_id": _call(call.name).tool_call_id})
    observed = guarded.execute(next_call)
    assert not observed.metadata.get("client_effect_deferred"), (
        "old deferred result escaped into new Run"
    )
    assert observed.metadata["historical_client_effect"] is True
    assert observed.tool_call_id == next_call.tool_call_id
    assert adapter.calls == 1 and adapter.reads == 1
    assert original.metadata["client_effect_deferred"] is True


@pytest.mark.parametrize("marker", [True, "malformed", 1])
def test_unreadable_or_malformed_deferred_cannot_escape_as_old_wait(marker):
    from agent_tools.effect_guard_support import reuse_result

    gateway, call = _Gateway(), _call("app.ui.item.open")
    stored = ToolResult(
        tool_call_id=call.tool_call_id,
        status=ToolCallStatus.EXECUTED,
        metadata={"client_effect_deferred": marker},
    )
    result = reuse_result(gateway, call, stored)
    assert result.metadata["execution_state"] == "unknown"
    assert not result.metadata.get("client_effect_deferred")
    assert gateway.calls == 0
