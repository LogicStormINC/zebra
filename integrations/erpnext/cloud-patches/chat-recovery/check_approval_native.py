"""Native parser + real canonical proposal-event evidence only; no model or mutation."""
from datetime import UTC, datetime
import json
import re
import sys
from uuid import UUID

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId
from agent_core.harness.evidence_ledger import EvidenceLedger, evidence_ledger
from agent_core.harness.models import HarnessEventDraft
from agent_core.harness.quality_gates import evaluate_answer
from agent_core.harness.task_contracts import infer_task_contract, parse_task_contract
from agent_storage.postgres.events import PostgresEventStore

def approval_preparation_contract(message, settings):
    if (settings.get('chat_readonly_enabled') is not True
            or settings.get('production_plan_proposals_enabled') is not True
            or not isinstance(message, str) or not 0 < len(message.strip()) <= 4000):
        return None
    # ponytail: narrow human-approval intent routing, not general language parsing.
    # Ambiguous/mixed or file deliverables keep native inference; a structured
    # Host business-intent field should replace this bounded route as scope grows.
    text = message.strip().lower()
    positive = re.sub(r"(?:不要|不允许|禁止|无需|不用|不得|不)(?:(?!而是|但是|然后|并且|但)[^，。；,;!?！？\n]){1,160}", '', text)
    positive = re.sub(r"\b(?:do not|don't|never|without)\b[^,.;!?\n]{1,160}", '', positive)
    plan = r'(?:production\s+plan|生产计划)'
    action = r'(?:新建|创建|修改|更新|提交|create|creation|update|submit|submission)'
    if (not re.search(plan, positive) or not re.search(r'审批|提案|待.{0,8}确认|等.{0,8}确认|确认后|人[工]?确认|approval|confirm|pending', text)
            or re.search(r'文件|报告|附件|导出|下载|发布|邮件|\b(?:artifact|pdf|xlsx?|excel|word|markdown|report|file|export|download|publish|email)\b', positive)
            or re.search(r'^(?:请)?(?:讨论|解释|说明|介绍|如何|怎么|是否|为什么|告诉我)|^(?:please\s+)?(?:discuss|explain|how|what|whether|should)\b', positive)
            or '?' in positive or '？' in positive):
        return None
    targets = re.findall(r'\bdoctype[\"\']?\s*[:=]\s*[\"\']?([a-z][a-z ]{0,60})', positive)
    if any(target.strip() != 'production plan' for target in targets):
        return None
    direct = action + r'\s*(?:(?:一张|一个)?(?:新的|这张|该|现有的)?|(?:(?:a|an|the)\s+)?(?:(?:new|existing)\s+)?)\s*' + plan
    reverse = plan + r'\s*' + action + r'(?:审批|提案|\s+approval)?'
    explicit = r'\boperation[\"\']?\s*[:=]\s*[\"\']?(?:create|update|submit)\b'
    if not (re.search(direct, positive) or re.search(reverse, positive)
            or 'erpnext.propose' in positive and re.search(explicit, positive)):
        return None
    remainder = re.sub(direct + '|' + reverse + '|' + explicit, '', positive)
    if re.search(r'新建|创建|修改|更新|提交|删除|取消|生成|\b(?:create|update|submit|change|modify|delete|cancel|generate)\b', remainder):
        return None
    return {'taskType': 'answer', 'goal': message.strip(),
        'requiredOutcomes': ['answer_present', 'evidence_collected'],
        'minCharacters': 1, 'requireStructure': False, 'requireEvidence': True,
        'requireCitations': False, 'requireVerification': False, 'requireArtifact': False,
        'versionScopes': []}

def main():
    config = json.load(sys.stdin)
    task_id = str(UUID(config['task_id']))
    values = conninfo_to_dict(config['dsn'])
    values['options'] = values.get('options', '') + ' -c default_transaction_read_only=on -c statement_timeout=10000'
    dsn = make_conninfo(**values)
    with psycopg.connect(dsn) as connection:
        assert connection.execute('SHOW transaction_read_only').fetchone()[0] == 'on'
        row = connection.execute('SELECT active_segment_id FROM agent_tasks WHERE deployment_namespace=%s AND task_id=%s', ('erpnext', task_id)).fetchone()
    assert row is not None
    events = PostgresEventStore(dsn, deployment_namespace='erpnext').list_for_session(SessionId(row[0]))
    goal = next(event.payload['content'] for event in reversed(events) if event.event_type is EventType.USER_MESSAGE_RECEIVED)
    raw = approval_preparation_contract(goal, {'chat_readonly_enabled': True, 'production_plan_proposals_enabled': True})
    assert raw is not None
    contract = parse_task_contract(raw, fallback_goal=goal)
    assert contract.task_type.value == 'answer' and not contract.require_artifact
    assert contract.required_outcomes == ('answer_present','evidence_collected') and contract.require_evidence_reference
    proposals = [event for event in events if event.event_type is EventType.TOOL_EXECUTION_COMPLETED
        and event.payload.get('tool_name') == 'erpnext.propose']
    assert proposals
    for event in proposals:
        receipt = json.loads(event.payload['output'])
        assert receipt.get('approval_required') is True and len(receipt.get('proposal_id', '')) == 64
    drafts = [HarnessEventDraft(event.event_type, event.actor, event.payload) for event in proposals]
    ledger = evidence_ledger(drafts)
    assert ledger.successful_tool_results == len(proposals) and not ledger.artifact_refs
    candidate = '审批已准备，等待你在助手面板独立确认；这不代表业务单据已创建、更新或提交。'
    assert evaluate_answer(goal, candidate, evidence=ledger, contract=contract).passed
    empty = evaluate_answer(goal, candidate, evidence=EvidenceLedger(), contract=contract)
    assert not empty.passed and 'verified_evidence' in empty.missing_requirements
    original = evaluate_answer(goal, candidate, evidence=ledger, contract=infer_task_contract(goal))
    assert not original.passed and 'required_artifact' in original.missing_requirements
    print(json.dumps({'native_contract_parsed': True, 'real_canonical_proposal_results': len(proposals),
        'requires_successful_tool_evidence': True, 'missing_evidence_refused': True,
        'artifact_not_required_for_approval_preparation': True, 'pending_not_business_success': True,
        'readonly_transaction': True, 'model_calls': 0, 'business_writes': 0}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'ok': False, 'error_class': type(error).__name__}))
        sys.exit(1)
