"""Fresh MODEL originals enter one publication/settlement owner hook."""

from agent_core.domain.coverage_model_checkpoint import decode_model_checkpoint
from agent_integrations.coverage_model_invocation import CoverageModelInvocation

from tests.agent_integrations.test_coverage_model_invocation import (
    compose,
    env,  # noqa: F401
    invoke,
)


def test_checkpoint_hook_runs_after_transport_and_before_usage(env):  # noqa: F811
    invocation, originals = compose(env), []

    def publish(identifier, body):
        checkpoint = decode_model_checkpoint(body)
        assert checkpoint.binding == env.binding
        assert identifier == checkpoint.artifact_id
        assert len(env.requests) == 1 and not env.budget.receipts
        originals.append(body)
        return CoverageModelInvocation._publish_checkpoint(invocation, identifier, body)

    invocation._publish_checkpoint = publish
    invoke(env, invocation)
    assert len(originals) == len(env.budget.receipts) == 1
    # An exact replay reads its existing original; it does not republish or send.
    invoke(env, invocation)
    assert len(originals) == len(env.requests) == 1
