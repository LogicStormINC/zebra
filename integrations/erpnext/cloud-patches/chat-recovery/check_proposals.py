"""Source contracts only; no production permissions, approvals or business writes fabricated."""
import ast
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent


def function(path, name):
    fn = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == name)
    fn.decorator_list = []
    return fn


def main():
    manifest = ROOT / 'frozen-manifest.json'
    if manifest.exists():
        for name, digest in json.loads(manifest.read_bytes())['files'].items():
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
    for path in ROOT.rglob('*.py'):
        ast.parse(path.read_text())
    policy = {}
    exec(compile((ROOT / 'storage/erp_chat_readonly.py').read_text(), '<actual-chat-policy>', 'exec'), policy)
    previous = dict(os.environ)
    try:
        os.environ.update(ZEBRA_ERPNEXT_CHAT_READONLY='enabled', ZEBRA_ERPNEXT_FRESH_AUTHORITY='enabled',
            ZEBRA_ERPNEXT_WORKSPACE_CONTAINMENT='enabled', ZEBRA_ERPNEXT_PRIVATE_WORKSPACES='disabled',
            ZEBRA_ERPNEXT_CHAT_SITE='erpnext.zebra.local', ZEBRA_ERPNEXT_PRODUCTION_PLAN_PROPOSALS='disabled')
        assert policy['allowed_tools']() == policy['TOOLS']
        os.environ['ZEBRA_ERPNEXT_PRODUCTION_PLAN_PROPOSALS'] = 'enabled'
        assert policy['allowed_tools']() == policy['TOOLS'] | {'erpnext.propose'}
        tool_fn = next(n for n in ast.walk(ast.parse((ROOT / 'worker/worker_tool_gateway.py').read_text()))
            if isinstance(n, ast.FunctionDef) and n.name == '_execute')
        worker_guard = next(n.test for n in tool_fn.body if isinstance(n, ast.If))
        for operation, doctype, denied in (('create','Production Plan',False), ('update','Production Plan',False),
                ('submit','Production Plan',False), ('create','Work Order',True), ('cancel','Production Plan',True),
                ('delete','Production Plan',True), ('action','Production Plan',True)):
            call = SimpleNamespace(name='erpnext.propose', arguments={'operation':operation,'arguments':{'doctype':doctype}})
            result = eval(compile(ast.Expression(worker_guard), '<actual-worker-proposal-guard>', 'eval'),
                dict(chat_enabled=policy['enabled'], allowed_tools=policy['allowed_tools'], READS=policy['READS'],
                    self=SimpleNamespace(host_context=SimpleNamespace(namespace_id='erpnext')), tool_call=call))
            assert result is denied
        os.environ['ZEBRA_ERPNEXT_PRODUCTION_PLAN_PROPOSALS'] = 'invalid'
        try:
            policy['allowed_tools']()
        except ValueError:
            pass
        else:
            raise AssertionError('invalid flag accepted')
    finally:
        os.environ.clear(); os.environ.update(previous)
    host_config = {'chat_readonly_enabled': True, 'production_plan_proposals_enabled': True}
    class Rejected(Exception):
        pass
    def fail(*args):
        raise Rejected()
    business = ast.parse((ROOT / 'host/business.py').read_text())
    writes = ast.literal_eval(next(n.value for n in business.body if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == 'WRITES' for t in n.targets)))
    schemas = ast.literal_eval(next(n.value for n in business.body if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == 'SCHEMAS' for t in n.targets)))
    metrics = ast.literal_eval(next(n.value for n in business.body if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == 'AGGREGATE_METRICS' for t in n.targets)))
    schema_fn = function(ROOT / 'host/gateway.py', 'business_arguments_schema')
    schema_fn.body = [n for n in schema_fn.body if not isinstance(n, ast.ImportFrom)]
    schema_scope = dict(SCHEMAS=schemas, AGGREGATE_METRICS=metrics)
    exec(compile(ast.Module(body=[schema_fn], type_ignores=[]), '<actual-business-json-schema>', 'exec'), schema_scope)
    read_schema = schema_scope['business_arguments_schema'](policy['READS'])
    fields = read_schema['properties']
    assert fields['metric']['enum'] == ['avg','count','max','min','sum']
    assert fields['limit'] == {'type':'integer','minimum':1,'maximum':50}
    assert fields['start']['maximum'] == 10000 and fields['fields']['maxItems'] == 30
    assert not {'function','aggregate_on','group_by','aggregate','limit_page_length'} & fields.keys()
    count = next(v for v in read_schema['anyOf'] if v['properties'].get('metric',{}).get('enum') == ['count'])
    assert set(count['required']) == {'doctype','metric'} and 'field' not in count['properties']
    numeric = next(v for v in read_schema['anyOf'] if v['properties'].get('metric',{}).get('enum') == ['avg','max','min','sum'])
    assert set(numeric['required']) == {'doctype','metric','field'}
    assert 'limit' not in count['properties'] and all(v['additionalProperties'] is False for v in read_schema['anyOf'])
    proposal_schema = schema_scope['business_arguments_schema']({'create','update','submit'})
    assert {'doctype','name','modified','values','company'} == set(proposal_schema['properties'])
    assert len(proposal_schema['anyOf']) == 3
    validate = function(ROOT / 'host/business.py', 'validate')
    host_guard = next(n for n in validate.body if isinstance(n, ast.If) and 'production_plan_proposals_enabled' in ast.unparse(n.test))
    for operation, doctype, denied in (('create','Production Plan',False), ('update','Production Plan',False),
            ('submit','Production Plan',False), ('create','Work Order',True), ('submit','Sales Order',True),
            ('cancel','Production Plan',True), ('upload_file','Production Plan',True)):
        rejected = False
        try:
            exec(compile(ast.Module(body=[host_guard], type_ignores=[]), '<actual-shared-business-guard>', 'exec'),
                dict(frappe=SimpleNamespace(conf={'zebra_agent':host_config}), operation=operation,
                    args={'doctype':doctype}, WRITES=writes, fail=fail))
        except Rejected:
            rejected = True
        assert rejected == denied
    # Exact native human-only boundary remains unchanged; model/tool confirmation is still refused.
    # Captured deployed105 Host AST pins; no external work/ directory is required.
    before = {'browser_confirmation': '5b9f77aa01aac9c171c9c4a44d74f2311d275f518e3e862c0f21ffff44bc5d56', 'execute': 'd971356d0b883aeb7699df175b1c446683dd87689f8bcad381e89791d908d59c', 'confirm': '1009b50a0824b4bb562dd5e58477035d26606207b3384c9519cc6222ee366e00', 'complete_approval': '24c3f669cacfa2b70ce45ad02fd1ac4d85097b508217733cfa756ccfbb5f192e', 'write': '863f3d3ad721fc53daeaadf75455462b36880e99851cf187df2c671d9a584637'}
    for name, digest in before.items():
        assert hashlib.sha256(ast.dump(function(ROOT / 'host/business.py', name)).encode()).hexdigest() == digest, name
    browser = function(ROOT / 'host/business.py', 'browser_confirmation')
    for tool, auth, cookie, csrf, method, denied in ((False,None,'sid','csrf','POST',False),
            (True,None,'sid','csrf','POST',True), (False,'token','sid','csrf','POST',True),
            (False,None,None,'csrf','POST',True), (False,None,'sid','wrong','POST',True),
            (False,None,'sid','csrf','GET',True)):
        import hmac
        headers = {'Authorization':auth,'X-Frappe-CSRF-Token':csrf}
        frappe = SimpleNamespace(flags={'zebra_tool_call':tool}, local=SimpleNamespace(request=SimpleNamespace(method=method,cookies={'sid':cookie})),
            session=SimpleNamespace(sid='sid',data={'csrf_token':'csrf'}),get_request_header=headers.get)
        scope = dict(frappe=frappe, authenticated=lambda:None, fail=fail, hmac=hmac)
        exec(compile(ast.Module(body=[browser], type_ignores=[]), '<native-browser-confirmation>', 'exec'), scope)
        rejected = False
        try:
            scope['browser_confirmation']()
        except Rejected:
            rejected = True
        assert rejected == denied
    print('PASS: typed read schemas and bounds; default-off Plan-only proposal guards; native cookie/CSRF confirmation unchanged')


if __name__ == '__main__':
    main()
