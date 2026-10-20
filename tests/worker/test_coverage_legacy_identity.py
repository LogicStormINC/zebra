"""Historical v1 write identity from pre-batch HEAD, not recomputed expectations."""

from datetime import UTC, datetime

from agent_core.domain.coverage_contracts import coverage_digest
from agent_core.domain.host_authority import HostResourceRef
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_integrations.coverage_snapshot_invocation import CoverageInvocation
from zebra_agent_worker.coverage_effect_validation import create_arguments, create_call_id

from tests.agent_core.test_coverage_task_admission import admission, host
from tests.agent_integrations.test_coverage_snapshot import frozen_manifest

EXPECTED_ARGUMENTS = {
    "history_ref": "history-1",
    "scope": {
        "time_field": "visible_at",
        "timezone": "UTC",
        "from_inclusive": "2029-12-31T00:00:00Z",
        "to_exclusive": "2030-01-01T00:00:00Z",
        "source_selection": "all_entitled_periods",
    },
    "contract_digest": "ab892202995a393c6df0c0f4898b017adfed4a7a46bc581d441de82c394600a1",
    "content_requirements": ["canonical_body"],
}


def test_historical_admission_digest_and_create_effect_identity_are_unchanged():
    value = admission()
    context = host().model_copy(update={"expires_at": datetime(2030, 1, 1, 1, tzinfo=UTC)})
    manifest = frozen_manifest()
    resource = HostResourceRef(type="trench.history", id="history-1")
    assert (
        coverage_digest(value.model_dump(mode="json"))
        == "362b081cacf38a5ff6061a4fc7addd9907382498b2ae3467f6dfb14920374926"
    )
    assert manifest.digest == "7fc96d7f1f25d7cc568e8ba5fddd61eeb3a391243386b9dc18e428293fee85bd"
    assert create_arguments(value) == EXPECTED_ARGUMENTS
    expected = "6264e86a-2834-565b-bcfb-1d1cf276c095"
    assert (
        str(create_call_id("legacy-golden", context, manifest, EXPECTED_ARGUMENTS, resource))
        == expected
    )
    calls = []

    def effect(call, authority, **kwargs):
        calls.append(call)
        assert call.arguments == EXPECTED_ARGUMENTS
        assert kwargs["required_resource"] == resource
        return ToolResult(
            tool_call_id=call.tool_call_id,
            status=ToolCallStatus.EXECUTED,
            output='{"status":"ready"}',
            created_at=datetime(2030, 1, 1, tzinfo=UTC),
        )

    source = CoverageInvocation(
        authority=context,
        history_ref="history-1",
        manifest=manifest,
        invoke=None,
        admitted_effect_invoke=effect,
        now=lambda: datetime(2030, 1, 1, tzinfo=UTC),
    )
    source.call(
        "create",
        {k: v for k, v in EXPECTED_ARGUMENTS.items() if k != "history_ref"},
        context,
        source.budget(context),
        "legacy-golden",
    )
    assert str(calls[0].tool_call_id) == expected
