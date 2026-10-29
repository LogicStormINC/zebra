"""Narrow Host approval-contract routing; all other tasks retain native inference."""
import ast
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent


def helper():
    fn = next(n for n in ast.parse((ROOT / 'host/chat.py').read_text()).body
        if isinstance(n, ast.FunctionDef) and n.name == 'approval_preparation_contract')
    scope = {'re': re}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<actual-host-contract>', 'exec'), scope)
    return scope['approval_preparation_contract']


def main():
    manifest = ROOT / 'frozen-manifest.json'
    if manifest.exists():
        for name, digest in json.loads(manifest.read_bytes())['files'].items():
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
    for path in ROOT.rglob('*.py'):
        ast.parse(path.read_text())
    classify = helper()
    settings = {'chat_readonly_enabled': True, 'production_plan_proposals_enabled': True}
    positives = [
        '为独立功能验收准备一张新的 Production Plan 创建审批。请只调用一次erpnext.propose，operation=create，arguments.doctype=Production Plan。审批返回后停止等待确认，不要宣称创建成功。values={"posting_date":"2026-10-28"}',
        '请新建生产计划，待我确认。', '请修改生产计划数量，待我确认。', '请更新生产计划，准备审批。',
        '请提交生产计划，等我确认。', 'Create a new Production Plan approval for me to confirm.',
        'Update the Production Plan approval, pending confirmation.', 'Submit Production Plan for approval.',
        '请新建一张新的生产计划，待我确认，不用生成文件。']
    for goal in positives:
        value = classify(goal, settings)
        assert value is not None, goal
        assert value['requiredOutcomes'] == ['answer_present', 'evidence_collected']
        assert value['requireEvidence'] is True and value['requireArtifact'] is False
        assert value['goal'] == goal.strip()
    negatives = ['只回复你好', '查询生产计划数量', '请说明如何创建生产计划审批',
        '讨论新建生产计划审批是否合适', '新建生产计划，待我确认，并生成PDF报告',
        '创建Production Plan审批，并导出Excel文件', '请新建Work Order审批，待我确认',
        '新建生产计划并修改销售订单，待我确认', '新建生产计划并提交Work Order，待我确认',
        '调用erpnext.propose operation=create arguments.doctype=Sales Order，为Production Plan准备审批',
        '不要创建生产计划，确认当前数量即可', '创建生产计划方案报告，待我确认',
        '请创建生产计划审批并生成生产工单，待我确认。',
        'Create a Production Plan approval and generate Work Orders, pending confirmation.']
    for goal in negatives:
        assert classify(goal, settings) is None, goal
    for key in settings:
        assert classify(positives[0], {**settings, key: False}) is None
    # The native-check copy is mechanically identical, not another classifier.
    native = next(n for n in ast.parse((ROOT / 'check_approval_native.py').read_text()).body
        if isinstance(n, ast.FunctionDef) and n.name == 'approval_preparation_contract')
    host = next(n for n in ast.parse((ROOT / 'host/chat.py').read_text()).body
        if isinstance(n, ast.FunctionDef) and n.name == 'approval_preparation_contract')
    assert ast.dump(native) == ast.dump(host)
    assert "'description': 'Agent task contract'" in (ROOT / 'host/chat.py').read_text()
    print('PASS: bounded approval contract routing; Chinese/English/JSON actions; files/discussion/mixed/default untouched')


if __name__ == '__main__':
    main()
