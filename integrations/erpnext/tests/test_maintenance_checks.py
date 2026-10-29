"""Run: python3 -B tests/test_maintenance_checks.py. Actual bootstrap/send guards, no services."""
import ast
from pathlib import Path
import subprocess
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT.parents[1] / 'work/maintenance-ux-live'
api_paths = [ROOT / 'zebra_erpnext/api.py']
front_paths = [ROOT / 'frontend/index.tsx']
if (LIVE / 'api.after.py').exists():
    api_paths.append(LIVE / 'api.after.py')
    front_paths.append(LIVE / 'index.after.tsx')
for path in api_paths:
    function = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == 'bootstrap')
    function.decorator_list = []
    frappe = SimpleNamespace(conf={}, get_list=lambda *a, **kw: [SimpleNamespace(name='QA')],
        defaults=SimpleNamespace(get_global_default=lambda key: 'QA'))
    scope = dict(frappe=frappe, cloud=SimpleNamespace(principal=lambda: 'qa-user'),
        chat=SimpleNamespace(MODEL_OPTIONS=[], REASONING_OPTIONS=[]))
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), scope)
    for value in (True, False, None, 'true', 1):
        frappe.conf['zebra_agent'] = {'enabled': True, 'admission_paused': value}
        result = scope['bootstrap']()
        assert result['enabled'] is True and result['admission_paused'] is (value is True)
        assert set(result) == {'user', 'companies', 'company', 'enabled', 'admission_paused', 'model_profile',
            'model_options', 'reasoning_options', 'reasoning_effort', 'https_url'}

# Execute the actual TypeScript functions after the already-installed esbuild transform.
# RPC doubles prove paused cached/fresh status prevents both submit and retry mutation.
subprocess.run(['node', '-', *map(str, front_paths)], cwd=ROOT, check=True, text=True, input=r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {transformSync} = require('esbuild');
(async () => {
 for (const path of process.argv.slice(2)) {
  const source = fs.readFileSync(path, 'utf8');
  const start = source.indexOf('  async function send(');
  const end = source.indexOf('  function pickSuggestion(', start);
  assert.ok(start >= 0 && end > start);
  const functions = transformSync(source.slice(start, end) + '\n globalThis.actions = {send' +
    (source.slice(start, end).includes('async function retryFresh') ? ', retryFresh' : '') + '};', {loader:'ts'}).code;
  const calls = [], errors = [];
  const context = {boot:{enabled:true,admission_paused:true}, text:'synthetic', readingFiles:false,
    sendGate:{current:false}, savingSettings:false, loadingSettings:false,
    state:{status:'idle',command_outcome:{retry_eligible:true,run_id:'run',accepted_event_id:'event'}},
    isActive:()=>false, setSending:()=>{}, setError:()=>{}, setNotice:()=>{},
    viewEpoch:{current:1}, selected:'owned', activeConversation:{current:'owned'},
    crypto:{randomUUID:()=> 'synthetic-id'},
    refreshBootstrap:async()=>{calls.push('bootstrap');return context.latest;},
    latest:{enabled:true,admission_paused:true},
    setState:()=>{calls.push('state-mutation');},
    api:async(method)=>{calls.push(method);throw new Error('safe generic RPC error');},
    fail:error=>errors.push(error.message),
    validateAttachmentBatch:()=>{}, filesRef:{current:[]}, model:'flash',reasoning:'high',
    pending:{current:null}, submissionIdentity:()=>false, pageContext:()=>({})};
  vm.createContext(context);vm.runInContext(functions, context);
  assert.equal(await context.actions.send(),false);
  if(context.actions.retryFresh) await context.actions.retryFresh();
  assert.deepEqual(calls,[]);
  context.boot.admission_paused=false;
  assert.equal(await context.actions.send(),false);
  assert.deepEqual(calls,['bootstrap']);calls.length=0;
  if(context.actions.retryFresh){await context.actions.retryFresh();assert.deepEqual(calls,['bootstrap']);calls.length=0;}
  context.latest.admission_paused=false;
  await assert.rejects(context.actions.send(),/safe generic RPC error/);
  assert.deepEqual(calls,['bootstrap','submit']);
  assert.deepEqual(errors,['safe generic RPC error']);
  assert.ok(source.includes('void refreshBootstrap().catch(fail)'));
  assert.ok(source.includes('refreshBootstrap().then(() => select(selected))'));
  assert.ok(source.includes('disabled={!boot?.enabled || boot.admission_paused === true'));
 }
 console.log('PASS actual cached/fresh maintenance guards, submit/retry refusal, unchanged RPC errors and refresh wiring');
})().catch(error=>{console.error(error);process.exitCode=1;});
''')
print('PASS actual bootstrap strict boolean for local and optional production-baseline candidates')
