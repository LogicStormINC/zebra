from agent_core.domain.agent_tasks import (
    ContextLifecycleController,
    ContextLifecycleDecision,
    ContextLifecycleSignals,
)


def test_lifecycle_controller_prefers_compaction_then_safe_rollover() -> None:
    controller = ContextLifecycleController()

    assert controller.decide(ContextLifecycleSignals()) is ContextLifecycleDecision.CONTINUE
    assert controller.decide(
        ContextLifecycleSignals(within_budget=False)
    ) is ContextLifecycleDecision.COMPACT
    assert controller.decide(
        ContextLifecycleSignals(
            within_budget=False,
            compaction_available=True,
            compaction_has_benefit=False,
        )
    ) is ContextLifecycleDecision.ROLLOVER
    assert controller.decide(
        ContextLifecycleSignals(agent_rollover_hint=True, pending_tool=True)
    ) is ContextLifecycleDecision.PAUSE
    assert controller.decide(
        ContextLifecycleSignals(agent_rollover_hint=True, uncertain_effect=True)
    ) is ContextLifecycleDecision.FAIL_CLOSED
