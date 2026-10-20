from types import SimpleNamespace
from unittest.mock import Mock

from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.harness.protocol_invariants import validate_tool_call_pairing
from agent_integrations.openai_payloads import serialize_message
from zebra_agent_worker.clarification_continuation import ClarificationContinuation
from zebra_agent_worker.continuation_dispatch import run_continuation

from tests.agent_runtime.test_crawl_source_http import call


def test_saved_private_clarification_rebases_evidence_and_answer_once():
    read, clarify = call("files.read", path="README.md"), call("agent.clarify", question="Which?")

    def message(role, content, **options):
        return SessionMessage(
            message_id=new_message_id(),
            role=role,
            content=content,
            created_at=read.created_at,
            **options,
        )

    private = {"provider_reasoning_required": True}
    conversation = (
        message(MessageRole.USER, "Find the company"),
        message(
            MessageRole.ASSISTANT, "Tool calls proposed.", tool_calls=(read,), metadata=private
        ),
        message(
            MessageRole.TOOL, "Existing authorized evidence", tool_call_id=str(read.tool_call_id)
        ),
        message(MessageRole.ASSISTANT, "Which company?", tool_calls=(clarify,), metadata=private),
    )
    state = {"contract_verification_prompted": True, "durable_action_fingerprints": ["retained"]}
    pending = ClarificationContinuation(
        clarify, "OPC社区", conversation, 3, 1, "Which company?", state
    )
    orchestrator = Mock()
    run_continuation(orchestrator, SimpleNamespace(), continuation=None, clarification=pending)
    orchestrator.continue_clarification.assert_not_called()
    args = orchestrator.continue_completed_tools.call_args.kwargs
    assert args["tool_calls"] == args["tool_results"] == ()
    messages = args["conversation"]
    validate_tool_call_pairing(list(messages))
    for item in messages:
        serialize_message(item, include_provider_reasoning=True)
    assert sum("OPC社区" in item.content for item in messages) == 1
    assert any("Existing authorized evidence" in item.content for item in messages)
    assert args["metadata"]["contract_verification_prompted"] is True
    assert "retained" in args["metadata"]["durable_action_fingerprints"]
    assert args["model_calls_used"] == 3 and args["tool_calls_executed"] == 1
    assert pending.metadata == state
