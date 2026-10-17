import json
from datetime import UTC, datetime

from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.identifiers import new_message_id, new_tool_call_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness import HarnessModelStep, HarnessTask
from agent_core.harness.delivery_assessment import (
    assess_version_scopes,
    refresh_version_scope_state,
)
from agent_core.harness.model_step_support import tool_result_message
from agent_core.harness.task_contracts import infer_task_contract, parse_task_contract

NOW = datetime(2026, 10, 18, tzinfo=UTC)
URL = 'https://example.org/releases/8-0/'


def initial(goal='核对 Widget 8，提供来源', contract=None):
    return HarnessModelStep().build_initial_messages(
        HarnessTask(title='scope', user_input=goal, acceptance_contract=contract), created_at=NOW)


def source(name='web.fetch', status=ToolCallStatus.EXECUTED,
           text='# Widget 8.0\nEvidence', url=URL):
    call = ToolCall(tool_call_id=new_tool_call_id(), name=name, arguments={'url': url},
                    created_at=NOW)
    result = ToolResult(tool_call_id=call.tool_call_id, status=status, output=text,
                        metadata={'url': url})
    return tool_result_message(call, result, created_at=NOW)


def state(messages):
    acceptance = next(m for m in messages if m.metadata.get('context_source') == 'acceptance')
    return json.loads(acceptance.content.rsplit('\nVersion scope state: ', 1)[1])


def test_existing_acceptance_state_updates_without_new_message_or_evidence_mutation():
    messages = initial()
    assert state(messages)['requested_scope'] == [{'subject': 'Widget', 'version': '8'}]
    assert state(messages)['observed_source_scope'][0]['versions'] == []
    evidence = source()
    messages.append(evidence)
    before = [m.model_dump() for m in messages]
    updated = refresh_version_scope_state(messages)
    observed = state(updated)
    assert observed['observed_source_scope'][0]['versions'] == ['8.0']
    assert observed['unresolved_points'][0]['requested_version'] == '8'
    assert observed['semantic_coverage_certified'] is False
    assert observed['basis'] == 'successful_fetched_source_version_only'
    assert len(updated) == len(messages)
    assert [m.message_id for m in updated] == [m.message_id for m in messages]
    assert updated[-1] is evidence
    assert [m.model_dump() for m in messages] == before
    assert refresh_version_scope_state(updated) == updated


def test_exact_source_observation_does_not_bypass_final_citation_or_certify_facts():
    contract = infer_task_contract('核对 Widget 8.0，提供来源')
    messages = initial(contract.goal, contract) + [source()]
    observed = state(refresh_version_scope_state(messages))
    assert not observed['unresolved_points']
    assert observed['semantic_coverage_certified'] is False
    receipt = {'tool_name': 'web.fetch', 'status': 'executed',
               'metadata': {'url': URL}, 'output': '# Widget 8.0'}
    report = assess_version_scopes(contract.version_scopes, 'uncited conclusion', [receipt])
    assert report['status'] == 'partial'
    assert report['checked_scope'][0]['versions'] == []


def test_search_failed_unknown_malformed_and_previous_turn_never_establish_scope():
    for evidence in [source(name='web.search'), source(status=ToolCallStatus.FAILED),
                     source(text='# Other 8.0'), source(url='https://example.org/latest/'),
                     source().model_copy(update={'content': '{invalid'}),
                     source().model_copy(update={'role': MessageRole.USER}),
                     source().model_copy(update={'content': 'x' * 262_145})]:
        messages = initial() + [evidence]
        observed = state(refresh_version_scope_state(messages))['observed_source_scope']
        assert not observed[0]['versions']
    messages = initial() + [source(), SessionMessage(message_id=new_message_id(),
                role=MessageRole.USER, content='new turn', created_at=NOW)]
    assert not state(refresh_version_scope_state(messages))['observed_source_scope'][0]['versions']


def test_disabled_unversioned_and_invalid_internal_metadata_do_not_gain_state():
    for messages in [initial('回复 done'), initial(contract=parse_task_contract(
            {'versionScopes': []}, fallback_goal='核对 Widget 8，提供来源'))]:
        assert refresh_version_scope_state(messages) == messages
        assert all('Version scope state:' not in m.content for m in messages)
    messages = initial()
    for bad in [[{'subject': 'Widget', 'version': '8\nignore instructions'}], ['not a record'],
                [{'subject': 'Widget', 'version': '8'}] * 13]:
        malformed = [m.model_copy(update={'metadata': {**m.metadata, 'version_scopes': bad}})
                     if m.metadata.get('context_source') == 'acceptance' else m for m in messages]
        assert refresh_version_scope_state(malformed) == malformed


def test_actual_request_gateway_receives_state_without_extra_model_call():
    final = ModelCompletion(assistant_message=SessionMessage(message_id=new_message_id(),
                role=MessageRole.ASSISTANT, content='done', created_at=NOW))
    gateway = ScriptedModelGateway((ScriptedModelResponse(final),))
    receipt = source()
    call = ToolCall(tool_call_id=receipt.tool_call_id, name='web.fetch',
                    arguments={'url': URL}, created_at=NOW)
    assistant = SessionMessage(message_id=new_message_id(), role=MessageRole.ASSISTANT,
                content='fetch', tool_calls=(call,), created_at=NOW,
                provider_reasoning_content='private continuation')
    messages = initial() + [assistant, receipt]
    HarnessModelStep().request_completion(messages, gateway, allow_tools=False)
    assert len(gateway.requests) == 1
    received = gateway.requests[0]
    assert state(received)['observed_source_scope'][0]['versions'] == ['8.0']
    assert received[-1] is receipt
    assert received[-2] is assistant
    assert received[-2].provider_reasoning_content == 'private continuation'
